"""
Event handling logic for macOS UI Monitoring.
This module handles processing and logging of UI events.
"""

import time
import json
import logging
from datetime import datetime
import threading
from typing import Dict, Any, Optional

from osmonitor.core.events import UIEvent
from osmonitor.utils.accessibility import clean_accessibility_value

logger = logging.getLogger(__name__)

def has_state_changed(current_state: Dict[str, Any], previous_state: Dict[str, Any]) -> bool:
    """
    Compare two state dictionaries to determine if there has been a meaningful change.
    
    Args:
        current_state: The current state dictionary
        previous_state: The previous state dictionary
        
    Returns:
        bool: True if there has been a meaningful change, False otherwise
    """
    # If either state is None, consider it a change
    if not current_state or not previous_state:
        return True
        
    # Check app changes
    current_app = current_state.get('app', {})
    previous_app = previous_state.get('app', {})
    if current_app.get('pid') != previous_app.get('pid'):
        return True
        
    # Check window changes
    if current_state.get('window_title') != previous_state.get('window_title'):
        return True
        
    # Check focused element changes
    current_element = current_state.get('element', {})
    previous_element = previous_state.get('element', {})
    if current_element.get('id') != previous_element.get('id'):
        return True
        
    # No significant changes detected
    return False

def add_event(self_obj, event: UIEvent):
    """Add an event to the history and notify callbacks.
    
    Args:
        self_obj: The MacOSUIMonitor instance
        event: The UIEvent to add
    """
    with self_obj._lock:
        self_obj.ui_events.append(event)
        # Trim history if needed
        if len(self_obj.ui_events) > self_obj.history_size:
            self_obj.ui_events = self_obj.ui_events[-self_obj.history_size:]
    
    # Capture screenshot for click events if enabled
    if event.event_type == "click" and self_obj.take_screenshots:
        pos = event.details.get("position", {})
        mouse_x = pos.get("x", 0)
        mouse_y = pos.get("y", 0)
        
        with self_obj._lock:
            self_obj.screenshot_counter += 1
            counter = self_obj.screenshot_counter
        
        # Get current element if available
        element = None
        if "element" in event.details and event.details["element"]:
            element = event.details["element"]
        
        from osmonitor.core.screenshot import capture_screenshot
        screenshot_path = capture_screenshot(
            self_obj.screenshot_dir, 
            (mouse_x, mouse_y),
            element,
            counter
        )
        
        # Add screenshot path to the event if screenshot was successful
        if screenshot_path:
            event.details["screenshot"] = screenshot_path
    
    # Write to output file if specified
    if self_obj.output_file:
        try:
            with open(self_obj.output_file, 'a') as f:
                f.write(json.dumps(event.to_dict()) + "\\n")
        except Exception as e:
            logger.error(f"Error writing to output file: {e}")
    
    # Write to consolidated timeline file if specified
    if self_obj.timeline_file:
        write_to_timeline(self_obj, event)
    
    notify_callbacks(self_obj, event)
    
    # If this is a click event, schedule a UI state update
    if event.event_type == "click":
        threading.Timer(0.5, self_obj._update_ui_state).start()

def log_ui_event(self_obj, event_type, details):
    """Log a UI event to the event history.
    
    Args:
        self_obj: The MacOSUIMonitor instance
        event_type: The type of event
        details: The event details
        
    Returns:
        UIEvent: The created event
    """
    event = UIEvent(event_type, time.time(), **details)
    add_event(self_obj, event)
    return event

def notify_callbacks(self_obj, event: UIEvent):
    """Notify callbacks registered for the event type.
    
    Args:
        self_obj: The MacOSUIMonitor instance
        event: The UIEvent to notify about
    """
    for callback in self_obj.callbacks.get(event.event_type, []):
        try:
            callback(event)
        except Exception as e:
            logger.error(f"Error in callback for {event.event_type}: {e}")

def write_to_timeline(self_obj, event: UIEvent):
    """Write an event to the consolidated timeline file.
    
    Args:
        self_obj: The MacOSUIMonitor instance
        event: The UIEvent to write
    """
    if not self_obj.timeline_file:
        return
        
    # Get the current application and window state
    app_name = "Unknown"
    window_title = "Unknown"
    try:
        if hasattr(self_obj, 'current_app') and self_obj.current_app:
            try:
                app_name = self_obj.current_app.element.get_title() or "Unknown"
            except:
                pass
                
        if hasattr(self_obj, 'current_window') and self_obj.current_window:
            try:
                window_title = self_obj.current_window.element.get_title() or "Unknown"
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
        if self_obj.timeline_format == 'json':
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
            prefix = ",\\n" if self_obj.timeline_entry_count > 0 else ""
            
            with open(self_obj.timeline_file, 'a') as f:
                f.write(f"{prefix}{json.dumps(entry)}")
            
            self_obj.timeline_entry_count += 1
            
        else:  # CSV format
            # Flatten the details to a string
            details_str = ";".join(f"{k}={v}" for k, v in details.items())
            
            with open(self_obj.timeline_file, 'a') as f:
                f.write(f"{event.timestamp},{event.event_type},{app_name},{window_title},{element_title},{element_role},{x},{y},{details_str}\\n")
    
    except Exception as e:
        logger.error(f"Error writing to timeline file: {e}")
