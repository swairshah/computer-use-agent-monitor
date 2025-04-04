"""
Main monitor class for macOS UI Monitoring.
This module provides the MacOSUIMonitor class that orchestrates all monitoring functionality.
"""

import time
import threading
import logging
import json
import os
from typing import Dict, List, Optional, Tuple, Any, Set, Callable, Union
from datetime import datetime

import AppKit
import subprocess

from macos_accessibility import ThreadSafeAXUIElement, MacOSUIElement, MacOSEngine, AXUIElementCreateApplication

# Import refactored modules
from osmonitor.core.ui_traversal import (
    traverse_ui_elements, 
    get_ui_data_via_applescript, 
    setup_accessibility_notifications,
    stop_observer
)
from osmonitor.core.app_detection import (
    get_frontmost_app_info,
    get_windows_for_app,
    run_apple_script
)
from osmonitor.core.event_handling import (
    add_event,
    log_ui_event,
    notify_callbacks,
    write_to_timeline,
    has_state_changed
)

from osmonitor.core.events import UIEvent
from osmonitor.core.elements import ElementInfo, ElementAttributes, WindowState, WindowIdentifier, UIFrame
from osmonitor.core.keyboard_monitor import KeyboardMonitor
from osmonitor.core.mouse_monitor import MouseMonitor
from osmonitor.core.text_selection import TextSelectionMonitor
from osmonitor.core.screenshot import capture_screenshot
from osmonitor.utils.accessibility import check_accessibility_permissions, clean_accessibility_value

logger = logging.getLogger(__name__)

# Applications to skip monitoring
SKIP_APPS = ["Finder", "SystemUIServer", "Dock", "ControlCenter", "NotificationCenter"]

# Check if PyObjC is available
# We're importing AppKit above so it's available
# TODO: handle cases where its not. 
HAS_APPKIT = True  

class MacOSUIMonitor:
    """Service that monitors the macOS UI state."""
    
    def __init__(self, history_size: int = 100, polling_interval: float = 0.2, 
                 log_level=logging.INFO, output_file=None, screenshot_dir=None,
                 take_screenshots=True, key_log_file=None, timeline_file="timeline.json",
                 timeline_format="json", monitor_text_selection=False, 
                 selection_interval=1.0):
        """Initialize the monitor.
        
        Args:
            history_size: Maximum number of events to keep in history
            polling_interval: Interval in seconds between polling the UI state
            log_level: Logging level to use
            output_file: Path to file where events should be saved as JSON lines
            screenshot_dir: Directory to save screenshots in
            take_screenshots: Whether to take screenshots on click events
            key_log_file: Path to a simplified log file just for keyboard events
            timeline_file: Path to a consolidated timeline file containing all events
            timeline_format: Format for the timeline file (json or csv)
            monitor_text_selection: Whether to monitor text selections
            selection_interval: Interval in seconds between checking for text selections
        """
        # Configure logger
        logger.setLevel(log_level)
        
        # Check accessibility permissions first
        check_accessibility_permissions()
        
        self.engine = MacOSEngine()
        self.system_wide = ThreadSafeAXUIElement.system_wide()
        
        self.current_app = None
        self.current_app_pid = None
        self.current_window = None
        self.current_element = None
        self.mouse_position = (0, 0)
        self.last_click_element = None
        self.last_click_position = None
        
        # For advanced app and window monitoring
        self.global_element_values = {}  # App -> Window -> WindowState
        self.current_context = {'app': None, 'window': None}
        self.lock = threading.RLock()  # For thread-safe access
        self.changed_windows = set()  # Track windows with changes
        self.is_traversing = False
        self.should_cancel_traversal = False
        self.named_pipe_handle = None  # For IPC
        
        # For state change tracking - only log events when state changes
        self.previous_state = None
        
        self.ui_events = []
        self.history_size = history_size
        self.output_file = output_file
        self.key_log_file = key_log_file
        self.timeline_file = timeline_file
        self.timeline_format = timeline_format
        
        # Create key log file directory if it exists
        if self.key_log_file:
            key_log_dir = os.path.dirname(os.path.abspath(self.key_log_file))
            os.makedirs(key_log_dir, exist_ok=True)
            
            # Add header to key log file
            with open(self.key_log_file, 'w') as f:
                f.write(f"# Keyboard event log started at {datetime.now().isoformat()}\n")
                f.write("# Format: timestamp,event_type,key,modifiers\n")
        
        # Create timeline file if specified
        if self.timeline_file:
            timeline_dir = os.path.dirname(os.path.abspath(self.timeline_file))
            os.makedirs(timeline_dir, exist_ok=True)
            
            # Initialize timeline file based on format
            if self.timeline_format == 'json':
                # Create a JSON file with an empty array
                with open(self.timeline_file, 'w') as f:
                    f.write('[\n')  # Start of JSON array, will be closed at the end
                self.timeline_entry_count = 0
            else:  # CSV format
                # Create a CSV file with headers
                with open(self.timeline_file, 'w') as f:
                    f.write("timestamp,event_type,app_name,window_title,element_title,element_role,x,y,details\n")
        
        # Screenshot settings
        self.take_screenshots = take_screenshots
        self.screenshot_dir = screenshot_dir
        self.screenshot_counter = 0
        
        self.polling_interval = polling_interval
        self.selection_interval = selection_interval
        self.monitor_text_selection = monitor_text_selection
        
        self.polling_thread = None
        
        self.running = False
        self.callbacks = {
            "click": [],
            "mouse_move": [],
            "scroll": [],
            "key_press": [],
            "key_release": [],
            "modifier_change": [],
            "focus_change": [],
            "app_change": [],
            "window_change": [],
            "text_selection": []  # Event type for text selections
        }
        
        # Thread safety
        self._lock = threading.RLock()
        
        # Initialize monitors
        self.keyboard_monitor = KeyboardMonitor(
            on_event_callback=self._add_event,
            key_log_file=key_log_file
        )
        
        self.mouse_monitor = MouseMonitor(
            system_wide=self.system_wide,
            on_event_callback=self._add_event
        )
        
        self.text_selection_monitor = None
        if monitor_text_selection:
            self.text_selection_monitor = TextSelectionMonitor(
                on_event_callback=self._add_event,
                current_app_getter=lambda: self.current_app,
                current_element_getter=lambda: self.current_element,
                interval=selection_interval,
                change_threshold=3.0  # Minimum seconds between selection events
            )
    
    def add_callback(self, event_type: str, callback: Callable[[UIEvent], None]):
        """Add a callback to be called when an event of the given type occurs."""
        if event_type in self.callbacks:
            self.callbacks[event_type].append(callback)
        else:
            logger.warning(f"Unknown event type: {event_type}")
    
    def _notify_callbacks(self, event: UIEvent):
        """Notify callbacks registered for the event type."""
        # Use the function from event_handling.py
        notify_callbacks(self, event)
    
    def _write_to_timeline(self, event: UIEvent):
        """Write an event to the consolidated timeline file."""
        # Use the function from event_handling.py
        write_to_timeline(self, event)
    
    def _add_event(self, event: UIEvent):
        """Add an event to the history and notify callbacks."""
        # Use the function from event_handling.py
        add_event(self, event)
    
    def _run_apple_script(self, script):
        """Run an AppleScript and return the result."""
        # Use the function from app_detection.py
        return run_apple_script(self, script)
    
    def _get_frontmost_app_info(self):
        """Get information about the frontmost application using multiple methods."""
        # Use the function from app_detection.py
        return get_frontmost_app_info(self)
    
    def _get_windows_for_app(self, app_pid):
        """Get windows for an application using AppleScript."""
        # Use the function from app_detection.py
        return get_windows_for_app(self, app_pid)
    
    def _update_ui_state(self):
        """Update the current UI state."""
        try:
            # Get the current state before any updates
            current_state = self.get_current_state()
            
            # Check if there's been a meaningful state change
            if has_state_changed(current_state, self.previous_state):
                logger.debug("State change detected, updating UI state")
                # Store the new state for next comparison
                self.previous_state = current_state
                
                # Use the enhanced monitoring approach - this will log events
                self._monitor_current_application()
            else:
                # No meaningful change, skip logging events
                logger.debug("No significant state change detected, skipping event logging")
        except Exception as e:
            logger.error(f"Error in _monitor_current_application: {e}")
            
            # Fall back to the original implementation if the new one fails
            with self._lock:
                # Get the frontmost app info
                frontmost_app = self._get_frontmost_app_info()
                if not frontmost_app:
                    logger.debug("Could not determine frontmost app")
                    return
                
                # Get app element using the PID
                app_pid = frontmost_app["pid"]
                app_name = frontmost_app["name"]
                method = frontmost_app.get("method", "Unknown")
                
                # Get the current state for comparison
                current_state = {
                    'app': {
                        'name': app_name,
                        'pid': app_pid
                    }
                }
                
                # Check if there's been an app change
                app_changed = (self.current_app_pid != app_pid)
                if app_changed:
                    # App has changed
                    old_app_name = None
                    if self.current_app:
                        try:
                            old_app_name = self.current_app.element.get_title()
                        except:
                            old_app_name = "Unknown"
                    
                    self.current_app_pid = app_pid
                    
                    try:
                        # Create a UI element for the app
                        app_element = ThreadSafeAXUIElement.application(app_pid)
                        new_app = MacOSUIElement(app_element)
                        self.current_app = new_app
                        
                        # Add app change event
                        self._add_event(UIEvent(
                            "app_change",
                            time.time(),
                            old_app=old_app_name,
                            new_app=app_name,
                            pid=app_pid,
                            method=method
                        ))
                        
                        logger.info(f"App changed to: {app_name} (PID: {app_pid})")
                        
                    except Exception as e:
                        logger.error(f"Error creating UI element for app {app_name}: {e}")
                
                # Get windows for the frontmost app
                windows = []
                try:
                    if self.current_app:
                        windows = self.current_app.element.get_windows()
                except Exception as e:
                    logger.debug(f"Error getting windows from UI element: {e}")
                
                window_changed = False
                window_title = "Unknown Window"
                
                # If no windows found via accessibility API, try AppleScript
                if not windows:
                    window_names = self._get_windows_for_app(app_pid)
                    if window_names:
                        # Use the first window name
                        window_title = window_names[0] if window_names else "Unknown Window"
                        current_state['window_title'] = window_title
                        
                        # Check if window has changed
                        old_window_title = "Unknown" if self.current_window is None else "Previous Window"
                        window_changed = (self.current_window is None or 
                                         (hasattr(self.current_window, 'window_title') and 
                                          self.current_window.window_title != window_title))
                        
                        if app_changed or window_changed:
                            # Add window change event
                            self._add_event(UIEvent(
                                "window_change",
                                time.time(),
                                old_window=old_window_title,
                                new_window=window_title,
                                method="AppleScript"
                            ))
                            
                            logger.info(f"Window changed to: {window_title} (via AppleScript)")
                            
                            # Clear current window since we can't get a real window element
                            self.current_window = None
                
                # If windows were found via accessibility API, use the first one
                elif windows and len(windows) > 0:
                    # The first window is usually the frontmost
                    new_window = MacOSUIElement(windows[0])
                    
                    # Check if window has changed
                    window_changed = (self.current_window is None or new_window.id() != self.current_window.id())
                    
                    if app_changed or window_changed:
                        old_window_title = "Unknown"
                        if self.current_window:
                            try:
                                raw_title = self.current_window.element.get_title()
                                old_window_title = clean_accessibility_value(raw_title) or "Previous Window"
                            except Exception as e:
                                logger.debug(f"Error getting old window title: {e}")
                                pass
                        
                        new_window_title = "Unknown"
                        try:
                            raw_title = new_window.element.get_title()
                            new_window_title = clean_accessibility_value(raw_title) or "Untitled Window"
                        except Exception as e:
                            logger.debug(f"Error getting window title: {e}")
                            pass
                        
                        self.current_window = new_window
                        window_title = new_window_title
                        current_state['window_title'] = window_title
                        
                        # Add window change event
                        self._add_event(UIEvent(
                            "window_change",
                            time.time(),
                            old_window=old_window_title,
                            new_window=new_window_title,
                            method="Accessibility"
                        ))
                        
                        logger.info(f"Window changed to: {new_window_title}")
                
                # Get focused element if we have a current app
                element_changed = False
                if self.current_app:
                    try:
                        focused_element = self.current_app.element.get_attribute("AXFocusedUIElement")
                        if focused_element:
                            new_element = MacOSUIElement(ThreadSafeAXUIElement(focused_element))
                            
                            # Check if element has changed
                            element_changed = (self.current_element is None or new_element.id() != self.current_element.id())
                            
                            if app_changed or window_changed or element_changed:
                                self.current_element = new_element
                                element_info = ElementInfo(new_element)
                                current_state['element'] = element_info.to_dict()
                                
                                # Add focus change event
                                self._add_event(UIEvent(
                                    "focus_change",
                                    time.time(),
                                    element=element_info.to_dict()
                                ))
                                
                                logger.info(f"Focus changed to: {element_info}")
                    except Exception as e:
                        logger.debug(f"Error getting focused element: {e}")
                        
                # Update previous state with the current state
                self.previous_state = current_state
    
    def _polling_loop(self):
        """Background thread that polls the UI state regularly."""
        logger.info("Polling thread started")
        while self.running:
            try:
                self._update_ui_state()
            except Exception as e:
                logger.error(f"Error updating UI state: {e}")
            
            time.sleep(self.polling_interval)
    
    def start(self):
        """Start monitoring the UI state."""
        if self.running:
            logger.warning("UI Monitor is already running")
            return
        
        self.running = True
        
        # Start the polling thread
        self.polling_thread = threading.Thread(target=self._polling_loop)
        self.polling_thread.daemon = True
        self.polling_thread.start()
        
        # Start the mouse monitor
        self.mouse_monitor.start()
        
        # Start the keyboard monitor
        self.keyboard_monitor.start()
        
        # Start text selection monitoring if enabled
        if self.monitor_text_selection and self.text_selection_monitor:
            self.text_selection_monitor.start()
        
        logger.info("MacOS UI Monitor started")
    
    def stop(self):
        """Stop monitoring the UI state."""
        if not self.running:
            logger.warning("UI Monitor is not running")
            return
        
        self.running = False
        
        # Stop the polling thread
        if self.polling_thread:
            self.polling_thread.join(timeout=1.0)
        
        # Stop the mouse monitor
        self.mouse_monitor.stop()
        
        # Stop the keyboard monitor
        self.keyboard_monitor.stop()
        
        # Stop the text selection monitor
        if self.text_selection_monitor:
            self.text_selection_monitor.stop()
        
        # Close the timeline JSON file if it's open and in JSON format
        if hasattr(self, 'timeline_file') and self.timeline_file and hasattr(self, 'timeline_format') and self.timeline_format == 'json':
            try:
                with open(self.timeline_file, 'a') as f:
                    f.write('\n]\n')  # Close the JSON array
                logger.info(f"Timeline written to {self.timeline_file}")
            except Exception as e:
                logger.error(f"Error closing timeline file: {e}")
        
        logger.info("MacOS UI Monitor stopped")
    
    def get_current_state(self):
        """Get the current UI state as a dictionary."""
        with self._lock:
            state = {
                "timestamp": time.time(),
                "mouse_position": {"x": self.mouse_position[0], "y": self.mouse_position[1]}
            }
            
            # First try to get app info directly with frontmost_app_info
            frontmost_app = self._get_frontmost_app_info()
            if frontmost_app:
                state["current_app"] = {
                    "name": frontmost_app["name"],
                    "pid": frontmost_app["pid"],
                    "method": frontmost_app.get("method", "Unknown")
                }
            elif self.current_app:
                # Fall back to our stored current_app
                try:
                    app_name = self.current_app.element.get_title()
                    app_id = self.current_app.id()
                    state["current_app"] = {
                        "name": app_name,
                        "id": app_id,
                        "method": "stored"
                    }
                except:
                    state["current_app"] = {
                        "name": "Unknown",
                        "id": self.current_app_pid,
                        "method": "fallback"
                    }
            else:
                state["current_app"] = {"name": "Unknown", "id": None, "method": "none"}
            
            # Get window info
            window_title = "Unknown"
            if self.current_window:
                try:
                    raw_title = self.current_window.element.get_title()
                    window_title = clean_accessibility_value(raw_title) or "Untitled Window"
                except Exception as e:
                    logger.debug(f"Error getting window title in state: {e}")
                    pass
            elif frontmost_app:
                # Try to get window via AppleScript
                window_names = self._get_windows_for_app(frontmost_app["pid"])
                if window_names:
                    window_title = window_names[0]
            
            state["current_window"] = {
                "title": window_title
            }
            
            # Get focused element info
            if self.current_element:
                try:
                    state["current_element"] = ElementInfo(self.current_element).to_dict()
                except:
                    state["current_element"] = {"error": "Could not get element info"}
            
            return state
    
    def get_recent_events(self, count=None, event_type=None):
        """Get recent UI events, optionally filtered by type."""
        with self._lock:
            events = self.ui_events
            
            if event_type:
                events = [e for e in events if e.event_type == event_type]
            
            if count:
                events = events[-count:]
            
            return [e.to_dict() for e in events]
            
    def _log_ui_event(self, event_type, details):
        """Log a UI event to the event history."""
        # Use the function from event_handling.py
        return log_ui_event(self, event_type, details)
        
    def _get_frontmost_application(self):
        """Get information about the frontmost application."""
        return self._get_frontmost_app_info()
        
    def _get_focused_window_name(self, app):
        """Get the focused window name for an application."""
        if not app or 'pid' not in app:
            return "Unknown Window"
            
        window_names = self._get_windows_for_app(app['pid'])
        return window_names[0] if window_names else "Unknown Window"
    
    def _write_to_pipe(self, ui_frame):
        """Write UI frame data to the named pipe if configured."""
        # Use the function from ui_traversal.py
        write_to_pipe(self, ui_frame)
    
    def _traverse_ui_elements(self, ax_app, app_name, window_name):
        """Traverse UI elements of the application to build element tree."""
        # Use the function from ui_traversal.py
        traverse_ui_elements(self, ax_app, app_name, window_name)
    
    def _setup_accessibility_notifications(self, pid, ax_app, app_name, window_name):
        """Set up accessibility notifications for the application."""
        # Use the function from ui_traversal.py
        setup_accessibility_notifications(self, pid, ax_app, app_name, window_name)
    
    def _stop_observer(self):
        """Stop any running accessibility observers."""
        # Use the function from ui_traversal.py
        stop_observer(self)
    
    def _monitor_current_application(self):
        """Monitor the current frontmost application."""
        # Cancel any in-progress traversal
        if self.is_traversing:
            self.should_cancel_traversal = True
            time.sleep(0.1)  # Give time for cancellation
        
        # Stop previous monitoring if any
        self._stop_observer()
        
        # Get frontmost application
        app = self._get_frontmost_application()
        if app is None:
            logger.warning("No frontmost application found")
            self._log_ui_event("warning", {"message": "No frontmost application found"})
            return
        
        # Sanitize app name
        app_name = app['name']
        
        # Skip ignored apps
        if app_name in SKIP_APPS:
            logger.info(f"Skipping ignored app: {app_name}")
            self._log_ui_event("app_skipped", {"app": app_name, "reason": "in skip list"})
            return
        
        # Get window name
        window_name = self._get_focused_window_name(app)
        
        # Check if app or window has changed from previous state
        app_changed = False
        window_changed = False
        
        if self.previous_state:
            prev_app = self.previous_state.get('app', {})
            prev_app_pid = prev_app.get('pid')
            prev_window = self.previous_state.get('window_title')
            
            app_changed = (prev_app_pid != app.get('pid'))
            window_changed = (prev_window != window_name)
        else:
            # If no previous state, consider it a change
            app_changed = True
            window_changed = True
            
        # Log application focus change only if it changed
        if app_changed:
            self._log_ui_event("app_focus", {
                "app": app_name, 
                "window": window_name, 
                "pid": app.get('pid', 'unknown')
            })
        
        # Initialize data structures for this app/window
        with self.lock:
            if app_name not in self.global_element_values:
                self.global_element_values[app_name] = {}
            if window_name not in self.global_element_values[app_name]:
                self.global_element_values[app_name][window_name] = WindowState()
                
            # Set current context
            self.current_context = {'app': app_name, 'window': window_name}
        
        # Check if we already have recent data
        window_exists = (app_name in self.global_element_values and 
                        window_name in self.global_element_values[app_name])
        
        if window_exists:
            window_state = self.global_element_values[app_name][window_name]
            time_diff = (datetime.now() - window_state.timestamp).total_seconds()
            is_window_recent = time_diff < 300  # 5 minutes
            
            if is_window_recent and window_changed:
                self._log_ui_event("window_revisit", {
                    "app": app_name,
                    "window": window_name,
                    "last_seen_seconds_ago": int(time_diff)
                })
        else:
            is_window_recent = False
            if window_changed:
                self._log_ui_event("window_new", {
                    "app": app_name,
                    "window": window_name
                })
        
        # Decide how to get UI information based on available APIs
        if HAS_APPKIT and 'pid' in app:
            # Use Accessibility API approach
            logger.info(f"Using Accessibility API for {app_name}, window: {window_name}")
            ax_app = AXUIElementCreateApplication(app['pid'])
            
            # Traverse UI elements if needed
            if not window_exists or not is_window_recent:
                if app_changed or window_changed:
                    self._log_ui_event("traversal_start", {
                        "app": app_name,
                        "window": window_name,
                        "reason": "new window" if not window_exists else "window data expired"
                    })
                self._traverse_ui_elements(ax_app, app_name, window_name)
            else:
                logger.info(f"Reusing existing UI elements for {app_name}")
                if app_changed or window_changed:
                    self._log_ui_event("traversal_skip", {
                        "app": app_name,
                        "window": window_name,
                        "reason": "recent data available"
                    })
                
            # Set up accessibility notifications
            self._setup_accessibility_notifications(app['pid'], ax_app, app_name, window_name)
        else:
            # Use AppleScript fallback approach
            logger.info(f"Using AppleScript fallback for {app_name}, window: {window_name}")
            if app_changed or window_changed:
                self._log_ui_event("fallback_mode", {
                    "app": app_name,
                    "window": window_name,
                    "method": "AppleScript",
                    "reason": "PyObjC not available" if not HAS_APPKIT else "PID not available"
                })
            self._get_ui_data_via_applescript(app_name, window_name)
    
    def _get_ui_data_via_applescript(self, app_name, window_name):
        """Get UI data using AppleScript as a fallback."""
        # Use the function from ui_traversal.py
        get_ui_data_via_applescript(self, app_name, window_name)
