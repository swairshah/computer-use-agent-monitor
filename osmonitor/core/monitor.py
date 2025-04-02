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

from macos_accessibility import ThreadSafeAXUIElement, MacOSUIElement, MacOSEngine

from osmonitor.core.events import UIEvent
from osmonitor.core.elements import ElementInfo
from osmonitor.core.keyboard_monitor import KeyboardMonitor
from osmonitor.core.mouse_monitor import MouseMonitor
from osmonitor.core.text_selection import TextSelectionMonitor
from osmonitor.core.screenshot import capture_screenshot
from osmonitor.utils.accessibility import check_accessibility_permissions, clean_accessibility_value

logger = logging.getLogger(__name__)

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
        for callback in self.callbacks.get(event.event_type, []):
            try:
                callback(event)
            except Exception as e:
                logger.error(f"Error in callback for {event.event_type}: {e}")
    
    def _write_to_timeline(self, event: UIEvent):
        """Write an event to the consolidated timeline file."""
        if not self.timeline_file:
            return
            
        # Get the current application and window state
        app_name = "Unknown"
        window_title = "Unknown"
        try:
            if hasattr(self, 'current_app') and self.current_app:
                try:
                    app_name = self.current_app.element.get_title() or "Unknown"
                except:
                    pass
                    
            if hasattr(self, 'current_window') and self.current_window:
                try:
                    window_title = self.current_window.element.get_title() or "Unknown"
                except:
                    pass
        except:
            # Silently fail if we can't get app or window info
            pass
            
        # Get element info if present in event
        element_title = ""
        element_role = ""
        if "element" in event.details and event.details["element"]:
            element = event.details["element"]
            if isinstance(element, dict):
                element_title = element.get("title", "")
                element_role = element.get("role", "")
            
        # Get position info if present
        x = y = 0
        if "position" in event.details:
            pos = event.details["position"]
            if isinstance(pos, dict):
                x = pos.get("x", 0)
                y = pos.get("y", 0)
                
        # Handle details
        details = {}
        for key, value in event.details.items():
            if key not in ["element", "position"]:
                details[key] = value
        
        try:
            if self.timeline_format == 'json':
                # Write as JSON entry
                entry = {
                    "timestamp": event.timestamp,
                    "event_type": event.event_type,
                    "app_name": app_name,
                    "window_title": window_title,
                    "element_title": element_title,
                    "element_role": element_role,
                    "position": {"x": x, "y": y},
                    "details": details
                }
                
                # Add comma if not the first entry
                prefix = ",\n" if self.timeline_entry_count > 0 else ""
                
                with open(self.timeline_file, 'a') as f:
                    f.write(f"{prefix}{json.dumps(entry)}")
                
                self.timeline_entry_count += 1
                
            else:  # CSV format
                # Flatten the details to a string
                details_str = ";".join(f"{k}={v}" for k, v in details.items())
                
                with open(self.timeline_file, 'a') as f:
                    f.write(f"{event.timestamp},{event.event_type},{app_name},{window_title},{element_title},{element_role},{x},{y},{details_str}\n")
        
        except Exception as e:
            logger.error(f"Error writing to timeline file: {e}")
    
    def _add_event(self, event: UIEvent):
        """Add an event to the history and notify callbacks."""
        with self._lock:
            self.ui_events.append(event)
            # Trim history if needed
            if len(self.ui_events) > self.history_size:
                self.ui_events = self.ui_events[-self.history_size:]
        
        # Capture screenshot for click events if enabled
        if event.event_type == "click" and self.take_screenshots:
            pos = event.details.get("position", {})
            mouse_x = pos.get("x", 0)
            mouse_y = pos.get("y", 0)
            
            with self._lock:
                self.screenshot_counter += 1
                counter = self.screenshot_counter
            
            # Get current element if available
            element = None
            if "element" in event.details and event.details["element"]:
                element = event.details["element"]
            
            screenshot_path = capture_screenshot(
                self.screenshot_dir, 
                (mouse_x, mouse_y),
                element,
                counter
            )
            
            # Add screenshot path to the event if screenshot was successful
            if screenshot_path:
                event.details["screenshot"] = screenshot_path
        
        # Write to output file if specified
        if self.output_file:
            try:
                with open(self.output_file, 'a') as f:
                    f.write(json.dumps(event.to_dict()) + "\n")
            except Exception as e:
                logger.error(f"Error writing to output file: {e}")
        
        # Write to consolidated timeline file if specified
        if self.timeline_file:
            self._write_to_timeline(event)
        
        self._notify_callbacks(event)
        
        # If this is a click event, schedule a UI state update
        if event.event_type == "click":
            threading.Timer(0.5, self._update_ui_state).start()
    
    def _run_apple_script(self, script):
        """Run an AppleScript and return the result."""
        try:
            result = subprocess.run(['osascript', '-e', script], 
                                   capture_output=True, text=True, timeout=1.0)
            if result.returncode == 0:
                return result.stdout.strip()
            else:
                logger.debug(f"AppleScript error: {result.stderr}")
                return None
        except Exception as e:
            logger.debug(f"Error running AppleScript: {e}")
            return None
    
    def _get_frontmost_app_info(self):
        """Get information about the frontmost application using multiple methods."""
        # Method 1: Using NSWorkspace
        try:
            workspace = AppKit.NSWorkspace.sharedWorkspace()
            frontmost_app = workspace.frontmostApplication()
            
            if frontmost_app:
                app_name = frontmost_app.localizedName()
                app_pid = frontmost_app.processIdentifier()
                bundle_id = frontmost_app.bundleIdentifier() or ""
                
                return {
                    "name": app_name,
                    "pid": app_pid,
                    "bundle_id": bundle_id,
                    "method": "NSWorkspace"
                }
        except Exception as e:
            logger.debug(f"NSWorkspace method failed: {e}")
        
        # Method 2: Using AppleScript
        script = """
        tell application "System Events"
            set frontApp to first application process whose frontmost is true
            set frontAppName to name of frontApp
            set frontAppPID to unix id of frontApp
            return frontAppName & ":" & frontAppPID
        end tell
        """
        result = self._run_apple_script(script)
        if result and ":" in result:
            app_name, app_pid_str = result.split(":", 1)
            try:
                app_pid = int(app_pid_str.strip())
                return {
                    "name": app_name.strip(),
                    "pid": app_pid,
                    "bundle_id": "",
                    "method": "AppleScript"
                }
            except ValueError:
                logger.debug(f"Could not parse PID from AppleScript: {app_pid_str}")
        
        # Method 3: Try using 'lsappinfo' command
        try:
            result = subprocess.run(['lsappinfo', 'front'], capture_output=True, text=True, timeout=1.0)
            if result.returncode == 0:
                output = result.stdout
                # Parse the ASN from the output
                asn = None
                for line in output.splitlines():
                    if "ASN:" in line:
                        asn = line.split("ASN:")[1].strip()
                        break
                
                if asn:
                    # Get app info using the ASN
                    info_result = subprocess.run(['lsappinfo', 'info', asn], 
                                                capture_output=True, text=True, timeout=1.0)
                    if info_result.returncode == 0:
                        info_output = info_result.stdout
                        app_name = None
                        app_pid = None
                        
                        for line in info_output.splitlines():
                            if "display name" in line.lower():
                                app_name = line.split('=')[1].strip(' "')
                            elif "pid" in line.lower():
                                try:
                                    app_pid = int(line.split('=')[1].strip())
                                except ValueError:
                                    pass
                        
                        if app_name and app_pid:
                            return {
                                "name": app_name,
                                "pid": app_pid,
                                "bundle_id": "",
                                "method": "lsappinfo"
                            }
        except Exception as e:
            logger.debug(f"lsappinfo method failed: {e}")
        
        # Method 4: Use ps command to get active GUI apps
        try:
            # Get list of foreground GUI apps (those with a window)
            ps_result = subprocess.run(['ps', '-axco', 'pid,command'], 
                                     capture_output=True, text=True, timeout=1.0)
            if ps_result.returncode == 0:
                lines = ps_result.stdout.strip().split('\n')
                gui_apps = []
                
                for line in lines[1:]:  # Skip header line
                    parts = line.strip().split(None, 1)
                    if len(parts) == 2:
                        try:
                            pid = int(parts[0])
                            command = parts[1]
                            
                            # Filter out obvious background processes
                            if (not command.endswith('helper') and
                                not command.startswith('com.apple.') and
                                not command == 'launchd' and
                                not command == 'kernel_task'):
                                gui_apps.append((pid, command))
                        except ValueError:
                            continue
                
                # Use process with lowest PID as a fallback
                if gui_apps:
                    gui_apps.sort()  # Sort by PID
                    pid, command = gui_apps[0]
                    return {
                        "name": command,
                        "pid": pid,
                        "bundle_id": "",
                        "method": "ps"
                    }
        except Exception as e:
            logger.debug(f"ps method failed: {e}")
        
        # If we still have a current_app_pid, use that as last resort
        if self.current_app_pid:
            return {
                "name": "Unknown App",
                "pid": self.current_app_pid,
                "bundle_id": "",
                "method": "fallback"
            }
        
        return None
    
    def _get_windows_for_app(self, app_pid):
        """Get windows for an application using AppleScript."""
        try:
            # Try using direct System Events query
            script = f"""
            tell application "System Events"
                set appProcess to first process whose unix id is {app_pid}
                set windowNames to name of windows of appProcess
                return windowNames
            end tell
            """
            result = self._run_apple_script(script)
            
            if result:
                # Parse output - typically a comma-separated list
                windows = [w.strip() for w in result.split(',')]
                if windows and windows[0]:
                    return windows
            
            # Try alternate script for getting window titles
            script = f"""
            tell application "System Events"
                set frontApp to first process whose unix id is {app_pid}
                set windowList to {{}}
                repeat with w in windows of frontApp
                    copy name of w to end of windowList
                end repeat
                return windowList
            end tell
            """
            result = self._run_apple_script(script)
            
            if result:
                windows = [w.strip() for w in result.split(',')]
                return [w for w in windows if w]
            
            return []
        except Exception as e:
            logger.debug(f"Error getting windows for app with PID {app_pid}: {e}")
            return []
    
    def _update_ui_state(self):
        """Update the current UI state."""
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
            
            logger.debug(f"Found frontmost app: {app_name} (PID: {app_pid}) via {method}")
            
            if self.current_app_pid != app_pid:
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
            
            # If no windows found via accessibility API, try AppleScript
            if not windows:
                window_names = self._get_windows_for_app(app_pid)
                if window_names:
                    logger.info(f"Found {len(window_names)} windows via AppleScript: {window_names}")
                    
                    # Use the first window name
                    window_name = window_names[0] if window_names else "Unknown Window"
                    
                    # Create a synthetic window change event
                    old_window_name = "Unknown" if self.current_window is None else "Previous Window"
                    
                    # Add window change event
                    self._add_event(UIEvent(
                        "window_change",
                        time.time(),
                        old_window=old_window_name,
                        new_window=window_name,
                        method="AppleScript"
                    ))
                    
                    logger.info(f"Window changed to: {window_name} (via AppleScript)")
                    
                    # Clear current window since we can't get a real window element
                    self.current_window = None
            
            # If windows were found via accessibility API, use the first one
            elif windows and len(windows) > 0:
                # The first window is usually the frontmost
                new_window = MacOSUIElement(windows[0])
                
                if self.current_window is None or new_window.id() != self.current_window.id():
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
            if self.current_app:
                try:
                    focused_element = self.current_app.element.get_attribute("AXFocusedUIElement")
                    if focused_element:
                        new_element = MacOSUIElement(ThreadSafeAXUIElement(focused_element))
                        
                        if self.current_element is None or new_element.id() != self.current_element.id():
                            self.current_element = new_element
                            element_info = ElementInfo(new_element)
                            
                            # Add focus change event
                            self._add_event(UIEvent(
                                "focus_change",
                                time.time(),
                                element=element_info.to_dict()
                            ))
                            
                            logger.info(f"Focus changed to: {element_info}")
                except Exception as e:
                    logger.debug(f"Error getting focused element: {e}")
    
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