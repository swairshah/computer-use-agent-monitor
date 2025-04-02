"""
macOS UI Monitoring service.
This module provides a background service that monitors the state of the UI,
tracking which application is active, which element is under the cursor,
which elements were clicked, etc.
"""

import time
import threading
import logging
from logging.handlers import RotatingFileHandler  # Added for file logging
import subprocess
import argparse
import json
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any, Set, Callable, Union
import ctypes
import re

# Import pynput for reliable keyboard monitoring
try:
    from pynput import keyboard
except ImportError:
    print("Installing pynput for keyboard monitoring...")
    try:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pynput"])
        from pynput import keyboard
    except Exception as e:
        print(f"Error installing pynput: {e}")
        print("Keyboard monitoring may not work correctly.")
        # Create a dummy module as a fallback
        class DummyKeyboard:
            class Key:
                pass
            class Listener:
                def __init__(self, on_press=None, on_release=None):
                    pass
                def start(self):
                    pass
                def stop(self):
                    pass
                def __enter__(self):
                    return self
                def __exit__(self, exc_type, exc_val, exc_tb):
                    pass
        keyboard = DummyKeyboard()

# PyObjC imports
import AppKit
from Quartz import (
    CGEventGetLocation,
    CGEventGetIntegerValueField,
    CGEventGetFlags,
    kCGMouseEventPressure,
    kCGScrollWheelEventDeltaAxis1,
    kCGScrollWheelEventDeltaAxis2,
    kCGEventKeyDown,
    kCGEventKeyUp,
    kCGEventFlagsChanged,
    kCGEventScrollWheel,
    kCGEventLeftMouseDown,
    kCGEventRightMouseDown,
    kCGEventOtherMouseDown,
    kCGEventLeftMouseUp,
    kCGEventRightMouseUp,
    kCGEventOtherMouseUp,
    kCGEventMouseMoved,
    kCGMouseEventNumber,
    CGEventTapCreate,
    CGEventMaskBit,
    kCGEventTapOptionDefault,
    kCGHeadInsertEventTap,
    kCGSessionEventTap,
    CGEventTapEnable,
    CGDisplayCreateImage,
    CGMainDisplayID
)

# Import the macOS accessibility utilities
from macos_accessibility import ThreadSafeAXUIElement, MacOSUIElement, MacOSEngine

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Map of common key codes to their names for better readability
# Based on macOS virtual key codes
KEY_CODE_MAP = {
    0: "a",
    1: "s",
    2: "d",
    3: "f",
    4: "h",
    5: "g",
    6: "z",
    7: "x",
    8: "c",
    9: "v",
    11: "b",
    12: "q",
    13: "w",
    14: "e",
    15: "r",
    16: "y",
    17: "t",
    18: "1",
    19: "2",
    20: "3",
    21: "4",
    22: "6",
    23: "5",
    24: "=",
    25: "9",
    26: "7",
    27: "-",
    28: "8",
    29: "0",
    30: "]",
    31: "o",
    32: "u",
    33: "[",
    34: "i",
    35: "p",
    36: "Return",
    37: "l",
    38: "j",
    39: "\'",
    40: "k",
    41: ";",
    42: "\\",
    43: ",",
    44: "/",
    45: "n",
    46: "m",
    47: ".",
    48: "Tab",
    49: "Space",
    50: "`",
    51: "Delete",
    53: "Escape",
    55: "Command",
    56: "Shift",
    57: "Caps Lock",
    58: "Option",
    59: "Control",
    60: "Right Shift",
    61: "Right Option",
    62: "Right Control",
    63: "Function",
    96: "F5",
    97: "F6",
    98: "F7",
    99: "F3",
    100: "F8",
    101: "F9",
    103: "F11",
    105: "F13",
    106: "F16",
    107: "F14",
    109: "F10",
    111: "F12",
    113: "F15",
    114: "Help",
    115: "Home",
    116: "Page Up",
    117: "Forward Delete",
    118: "F4",
    119: "End",
    120: "F2",
    121: "Page Down",
    122: "F1",
    123: "Left Arrow",
    124: "Right Arrow",
    125: "Down Arrow",
    126: "Up Arrow",
}


def clean_accessibility_value(value: Any) -> str:
    """Clean and normalize values returned from the macOS Accessibility API.
    
    This handles the various formats and special values that the API can return,
    including tuples like (0, "Actual Value") and special markers like "<null>".
    
    Args:
        value: Any value returned from the Accessibility API
        
    Returns:
        A cleaned string representation of the value, or empty string if no useful value
    """
    if value is None:
        return ""
    
    # Handle PyObjC tuple returns (often in format (code, value))
    if isinstance(value, tuple):
        # If second element exists and isn't null, use it
        if len(value) > 1:
            second_val = value[1]
            if second_val != "<null>" and second_val is not None:
                # Return the cleaned second value
                return clean_accessibility_value(second_val)
        # Otherwise use the first value if it's not a number
        if len(value) > 0 and not isinstance(value[0], (int, float)):
            return clean_accessibility_value(value[0])
        # Default to empty string for numeric tuples like (0, None)
        return ""
    
    # Handle other types
    if isinstance(value, str):
        return value.strip()
    
    # If it's another type, convert to string but handle null markers
    string_val = str(value)
    if string_val == "<null>" or "NULL" in string_val:
        return ""
        
    return string_val.strip()

class UIEvent:
    """Represents a UI event like a click, key press, or focus change."""
    
    def __init__(self, event_type: str, timestamp: float, **kwargs):
        self.event_type = event_type  # click, key_press, focus_change, etc.
        self.timestamp = timestamp    # When the event occurred
        self.details = kwargs         # Additional event-specific details
    
    def __str__(self):
        details_str = ", ".join(f"{k}={v}" for k, v in self.details.items())
        return f"UIEvent({self.event_type}, {self.timestamp:.2f}, {details_str})"
    
    def to_dict(self):
        """Convert event to a serializable dictionary."""
        return {
            "type": self.event_type,
            "timestamp": self.timestamp,
            **self.details
        }


class ElementInfo:
    """Information about a UI element."""
    
    # Known accessibility attributes that often contain useful information
    IMPORTANT_ATTRIBUTES = [
        "AXRole", "AXTitle", "AXDescription", "AXValue", "AXHelp", 
        "AXLabel", "AXRoleDescription", "AXSubrole", "AXIdentifier",
        "AXPlaceholderValue", "AXSelectedText", "AXText", "AXDisplayedText",
        "AXPath", "AXName", "AXMenuItemCmdChar", "AXMenuItemCmdModifiers", 
        "AXMenuItemCmdVirtualKey", "AXMenuItemMarkChar", "AXTitleUIElement", 
        "AXParent", "AXChildren", "AXWindow", "AXTopLevelUIElement", "AXEnabled",
        "AXFocused", "AXVisible", "AXSelected", "AXExpanded", "AXRequired"
    ]
    
    def __init__(self, element: MacOSUIElement):
        """Initialize with a MacOSUIElement."""
        self.element = element
        self.id = element.id()
        self.raw_attributes = {}  # Store all raw attributes
        
        # Get role with better error handling
        try:
            raw_role = element.role()
            self.role = clean_accessibility_value(raw_role) or "Unknown"
            if not self.role:  # If empty after cleaning
                self.role = "Unknown"
        except Exception as e:
            self.role = f"Unknown ({str(e)[:30]})"
        
        # Get position with default fallback
        try:
            raw_pos = element.element.get_position()
            # For position, we need to handle it specially since we need the numeric values
            if isinstance(raw_pos, tuple) and len(raw_pos) == 2:
                self.position = raw_pos
            else:
                self.position = (0, 0)
        except Exception:
            self.position = (0, 0)
        
        # Get size with default fallback
        try:
            raw_size = element.element.get_size()
            # For size, we need to handle it specially since we need the numeric values
            if isinstance(raw_size, tuple) and len(raw_size) == 2:
                self.size = raw_size
            else:
                self.size = (0, 0)
        except Exception:
            self.size = (0, 0)
            
        # Store direct parent element's role (useful for context)
        try:
            parent_element = element.element.get_attribute("AXParent")
            if parent_element:
                parent = MacOSUIElement(ThreadSafeAXUIElement(parent_element))
                self.parent_role = clean_accessibility_value(parent.role())
            else:
                self.parent_role = ""
        except Exception:
            self.parent_role = ""
            
        # Get all attributes and store them
        try:
            # Get all available attributes 
            attrs = element.attributes() or {}
            self.raw_attributes = attrs
            
            # Set basic attributes with empty defaults
            self.title = ""
            self.value = ""
            self.description = ""
            self.help = ""
            self.identifier = ""
            self.label = ""
            self.subrole = ""
            self.placeholder = ""
            self.selected_text = ""
            self.text = ""
            self.displayed_text = ""
            self.name = ""
            self.path = ""
            self.url = ""
            self.role_description = ""
            
            # Status attributes
            self.enabled = True
            self.focused = False
            self.visible = True
            self.selected = False
            self.expanded = False
            self.required = False
            
            # Process direct attribute mapping
            direct_mapping = {
                "value": "AXValue",
                "description": "AXDescription",
                "help": "AXHelp",
                "identifier": "AXIdentifier",
                "label": "AXLabel",
                "subrole": "AXSubrole",
                "placeholder": "AXPlaceholderValue",
                "selected_text": "AXSelectedText",
                "text": "AXText",
                "displayed_text": "AXDisplayedText",
                "name": "AXName", 
                "path": "AXPath",
                "url": "AXURL",
                "role_description": "AXRoleDescription",
                "enabled": "AXEnabled",
                "focused": "AXFocused",
                "visible": "AXVisible",
                "selected": "AXSelected", 
                "expanded": "AXExpanded",
                "required": "AXRequired"
            }
            
            # Set attributes from mapping
            for attr_name, ax_name in direct_mapping.items():
                if ax_name in attrs:
                    raw_value = attrs.get(ax_name)
                    if attr_name in ["enabled", "focused", "visible", "selected", "expanded", "required"]:
                        # For boolean attributes, convert but keep as boolean
                        if raw_value is not None:
                            setattr(self, attr_name, bool(raw_value))
                    else:
                        # For text attributes, clean the value
                        setattr(self, attr_name, clean_accessibility_value(raw_value))
            
            # Try specific approach for title - sometimes needs special handling
            try:
                raw_title = element.element.get_title()
                self.title = clean_accessibility_value(raw_title)
            except Exception:
                # If direct method fails, try to get from attributes
                self.title = clean_accessibility_value(attrs.get("AXTitle", ""))
            
            # If we have a TitleUIElement, try to get its value
            if not self.title and "AXTitleUIElement" in attrs:
                try:
                    title_elem = attrs.get("AXTitleUIElement")
                    if title_elem:
                        title_ui = MacOSUIElement(ThreadSafeAXUIElement(title_elem))
                        title_value = title_ui.element.get_title() or title_ui.element.get_attribute("AXValue")
                        if title_value:
                            self.title = clean_accessibility_value(title_value)
                except Exception:
                    pass
             
            # Get additional attributes that might help identify menu items
            if self.role == "AXMenuItem" or self.subrole == "AXMenuItem":
                self.menu_cmd_char = clean_accessibility_value(attrs.get("AXMenuItemCmdChar", ""))
                self.menu_mark_char = clean_accessibility_value(attrs.get("AXMenuItemMarkChar", ""))
            
            # Get child count
            try:
                children = attrs.get("AXChildren", [])
                self.child_count = len(children) if children else 0
            except Exception:
                self.child_count = 0
            
            # If title is STILL empty, try alternative attributes as fallbacks
            if not self.title:
                for attr in [self.label, self.value, self.name, self.description, 
                            self.text, self.displayed_text, self.selected_text, 
                            self.placeholder, self.menu_cmd_char, self.menu_mark_char]:
                    if attr:
                        self.title = clean_accessibility_value(attr)
                        break
                        
            # Last resort: try using role description if we have no title
            if not self.title and self.role_description:
                self.title = f"[{self.role_description}]"
                
            # Try to get frame geometry for better positioning
            try:
                frame = attrs.get("AXFrame", None)
                if frame and isinstance(frame, dict):
                    origin = frame.get("origin", {})
                    size = frame.get("size", {})
                    x = origin.get("x", self.position[0])
                    y = origin.get("y", self.position[1])
                    width = size.get("width", self.size[0])
                    height = size.get("height", self.size[1])
                    self.position = (x, y)
                    self.size = (width, height)
            except Exception:
                # Keep existing position/size if this fails
                pass
                
        except Exception as e:
            logger.debug(f"Error getting element attributes: {e}")
            # Keep the defaults set earlier
    
    def __str__(self):
        title_str = f'"{self.title}"' if self.title else "No title"
        context = []
        
        # Add most relevant context attributes
        if self.role_description:
            context.append(self.role_description)
        elif self.role:
            context.append(self.role)
        
        if self.subrole:
            context.append(f"subrole:{self.subrole}")
            
        if self.parent_role:
            context.append(f"in:{self.parent_role}")
            
        if self.child_count > 0:
            context.append(f"children:{self.child_count}")
            
        # Add enabled/selected status if not the default
        if not self.enabled:
            context.append("disabled")
        if self.selected:
            context.append("selected")
        if self.focused:
            context.append("focused")
            
        context_str = ", ".join(context)
        
        return f"{title_str} ({context_str})"
    
    def to_dict(self):
        """Convert element info to a serializable dictionary."""
        # Base attributes always included
        result = {
            "id": self.id,
            "role": self.role,
            "title": self.title,
            "position": {"x": self.position[0], "y": self.position[1]},
            "size": {"width": self.size[0], "height": self.size[1]}
        }
        
        # Include status attributes
        status = {}
        for attr_name in ["enabled", "focused", "visible", "selected", "expanded", "required"]:
            value = getattr(self, attr_name, None)
            if value is not None:  # Include all booleans, even False
                status[attr_name] = value
                
        if status:
            result["status"] = status
            
        # Add parent information if available
        if self.parent_role:
            result["parent_role"] = self.parent_role
            
        # Add child count if available
        if hasattr(self, 'child_count') and self.child_count > 0:
            result["child_count"] = self.child_count
        
        # Add additional text attributes if they have values
        text_attrs = [
            "value", "description", "label", "identifier", "help",
            "subrole", "placeholder", "selected_text", "text", 
            "displayed_text", "name", "path", "url", "role_description"
        ]
        
        for attr_name in text_attrs:
            value = getattr(self, attr_name, "")
            if value:  # Only include non-empty values
                result[attr_name] = value
        
        # Add menu item specific attributes if present
        if hasattr(self, 'menu_cmd_char') and self.menu_cmd_char:
            result["menu_cmd_char"] = self.menu_cmd_char
            
        if hasattr(self, 'menu_mark_char') and self.menu_mark_char:
            result["menu_mark_char"] = self.menu_mark_char
                
        return result


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
        self._check_accessibility_permissions()
        
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
        self.keyboard_thread = None
        self.keyboard_listener = None
        self.selection_thread = None
        
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
            "text_selection": []  # New event type for text selections
        }
        
        # Selection tracking properties
        self.last_selection = None
        self.selection_change_threshold = 3  # Minimum seconds between selection events
        
        # Track modifier key state
        self.modifier_state = {
            "shift": False,
            "control": False,
            "option": False,
            "command": False,
            "fn": False,
            "capslock": False
        }
        
        # Thread safety
        self._lock = threading.RLock()
    
    def _check_accessibility_permissions(self, show_prompt=True):
        """Check if accessibility permissions are granted."""
        from HIServices import AXIsProcessTrustedWithOptions
        from CoreFoundation import CFDictionaryCreate, kCFTypeDictionaryKeyCallBacks, kCFTypeDictionaryValueCallBacks
        
        options = None
        if show_prompt:
            key = "AXTrustedCheckOptionPrompt"
            value = True
            options = CFDictionaryCreate(
                None,
                [key], [value],
                1,
                kCFTypeDictionaryKeyCallBacks,
                kCFTypeDictionaryValueCallBacks
            )
        
        is_trusted = AXIsProcessTrustedWithOptions(options)
        
        if is_trusted:
            logger.info("Accessibility permissions are granted")
            return True
        else:
            if show_prompt:
                logger.info("Accessibility permissions prompt displayed")
            else:
                logger.warning("Accessibility permissions not granted")
                logger.info("**************************************************************")
                logger.info("* ACCESSIBILITY PERMISSIONS REQUIRED                          *")
                logger.info("* Go to System Preferences > Security & Privacy > Privacy >   *")
                logger.info("* Accessibility and add this application.                     *")
                logger.info("* Without this permission, UI automation will not function.   *")
                logger.info("**************************************************************")
            
            return False
    
    def capture_screenshot(self, mouse_x, mouse_y):
        """Capture a screenshot of the main display with mouse coordinates."""
        if not self.screenshot_dir:
            logger.warning("Screenshot directory not set, not capturing screenshot")
            return None
            
        try:
            # Ensure screenshot directory exists
            os.makedirs(self.screenshot_dir, exist_ok=True)
            
            # Get main display ID
            display_id = CGMainDisplayID()
            
            # Create screenshot image
            screenshot = CGDisplayCreateImage(display_id)
            if screenshot is None:
                logger.error("Failed to create screenshot image")
                return None
            
            # Get width and height using the proper CoreGraphics functions
            from Quartz import CGImageGetWidth, CGImageGetHeight
            width = CGImageGetWidth(screenshot)
            height = CGImageGetHeight(screenshot)
            
            # Get the timestamp for the filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # Increment screenshot counter
            with self._lock:
                self.screenshot_counter += 1
                counter = self.screenshot_counter
            
            # Create filename with mouse coordinates and counter
            filename = f"screenshot_{counter:06d}_mouse_{int(mouse_x)}_{int(mouse_y)}_{timestamp}.png"
            
            # If we have element info, add a sanitized version of the title
            if hasattr(self, 'current_element') and self.current_element:
                try:
                    element_info = ElementInfo(self.current_element)
                    if element_info.title:
                        # Sanitize title for filename - keep only alphanumeric chars and replace others with underscore
                        import re
                        safe_title = re.sub(r'[^\w]', '_', element_info.title)[:30]  # Truncate to avoid too long filenames
                        filename = f"screenshot_{counter:06d}_{safe_title}_mouse_{int(mouse_x)}_{int(mouse_y)}_{timestamp}.png"
                except Exception:
                    pass  # If we can't get element info, just use the default filename
                
            filepath = os.path.join(self.screenshot_dir, filename)
            
            # Convert to NSImage and save
            # Use proper PyObjC bridging for CGImage to NSImage conversion
            ns_image = AppKit.NSImage.alloc().initWithCGImage_size_(screenshot, AppKit.NSMakeSize(width, height))
            
            # Create bitmap representation
            bitmap_rep = AppKit.NSBitmapImageRep.alloc().initWithData_(ns_image.TIFFRepresentation())
            
            # Convert to PNG data
            png_data = bitmap_rep.representationUsingType_properties_(
                AppKit.NSBitmapImageFileTypePNG, 
                {AppKit.NSImageCompressionFactor: 0.9}
            )
            
            # Write to file
            if png_data.writeToFile_atomically_(filepath, True):
                logger.info(f"Screenshot saved to {filepath}")
                return filepath
            else:
                logger.error(f"Failed to write screenshot to {filepath}")
                return None
            
        except Exception as e:
            logger.error(f"Error capturing screenshot: {e}")
            return None
    
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
            screenshot_path = self.capture_screenshot(mouse_x, mouse_y)
            
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
    
    def _setup_event_tap(self):
        """Set up an event tap to monitor keyboard and mouse events."""
        try:
            from CoreFoundation import (
                CFRunLoopGetCurrent, 
                CFRunLoopAddSource, 
                kCFRunLoopCommonModes,
                CFMachPortCreateRunLoopSource
            )
            
            # Log that we're setting up event tap
            logger.error("Setting up keyboard and mouse event tap")
            
            # First check if we have accessibility permissions
            if not self._check_accessibility_permissions(False):
                logger.error("ERROR: No accessibility permissions. Keyboard events will not be detected.")
                logger.error("Go to System Preferences > Security & Privacy > Privacy > Accessibility")
                logger.error("and add this application to the list.")
                return False
            
            # Create mask for all event types we want to monitor - FOCUS ON KEYBOARD ONLY
            event_mask = (
                CGEventMaskBit(kCGEventKeyDown) |
                CGEventMaskBit(kCGEventKeyUp) |
                CGEventMaskBit(kCGEventFlagsChanged)  # Used for modifier key changes
            )
            
            # Direct log function for debugging keyboard events
            def direct_log_key(message):
                """Write directly to a debug file to diagnose keyboard events"""
                try:
                    debug_path = "/tmp/keyboard_debug.log"
                    with open(debug_path, "a") as f:
                        f.write(f"{time.time()}: {message}\n")
                except:
                    pass  # Silent fail
            
            # Callback function for the event tap
            def event_callback(proxy, event_type, event, refcon):
                try:
                    # Write to debug file for any event with detailed event type info
                    event_type_name = "UNKNOWN"
                    if event_type == kCGEventKeyDown:
                        event_type_name = "kCGEventKeyDown"
                    elif event_type == kCGEventKeyUp:
                        event_type_name = "kCGEventKeyUp"
                    elif event_type == kCGEventFlagsChanged:
                        event_type_name = "kCGEventFlagsChanged"
                    direct_log_key(f"Event received: type={event_type} ({event_type_name})")
                    
                    # Process based on event type
                    if event_type == kCGEventKeyDown:
                        # Get key code and character
                        keycode = CGEventGetIntegerValueField(event, AppKit.kCGKeyboardEventKeycode)
                        
                        # Write direct debug
                        direct_log_key(f"KeyDown event: keycode={keycode}")
                        
                        # Try to convert keycode to character
                        char = ""
                        try:
                            # Create an NSEvent from the CGEvent to get the characters
                            ns_event = AppKit.NSEvent.eventWithCGEvent_(event)
                            if ns_event:
                                char = ns_event.characters() or ""
                                direct_log_key(f"Character: '{char}'")
                        except Exception as e:
                            direct_log_key(f"Error getting characters: {e}")
                                
                        # Get current modifier keys state
                        flags = CGEventGetFlags(event)
                        modifiers = self._parse_modifier_flags(flags)
                        direct_log_key(f"Modifiers: {modifiers}")
                        
                        # Add key name if available
                        key_name = KEY_CODE_MAP.get(keycode, "")
                        direct_log_key(f"Key name: '{key_name}'")
                        
                        # Write full key information to debug
                        key_display = char or key_name or f"keycode {keycode}"
                        direct_log_key(f"FULL KEY INFO: {key_display} with modifiers {modifiers}")
                        
                        # Record the key press event
                        self._add_event(UIEvent(
                            "key_press",
                            time.time(),
                            keycode=keycode,
                            character=char,
                            key_name=key_name,
                            modifiers=modifiers
                        ))
                        
                        key_display = char or key_name or f"keycode {keycode}"
                        # Build a comprehensive key press message with all details
                        mod_str = ""
                        active_mods = [name for name, active in modifiers.items() if active]
                        if active_mods:
                            mod_str = f" with modifiers: {'+'.join(active_mods)}"
                        
                        # Log to both root logger and our module logger for maximum visibility
                        msg = f"KEY PRESS: {key_display}{mod_str}"
                        # Use error level for maximum visibility in debugging
                        logger.error(msg)
                        
                        # Always write to the key log file (using a direct, more reliable method)
                        try:
                            timestamp = time.time()
                            mod_list = '+'.join(active_mods) if active_mods else ""
                            key_log_path = getattr(self, 'key_log_file', None) or "/tmp/keyboard_events.csv"
                            
                            # Use low-level file operations to ensure it's written
                            import os
                            log_fd = os.open(key_log_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
                            os.write(log_fd, f"{timestamp},key_press,{key_display},{mod_list}\n".encode('utf-8'))
                            os.close(log_fd)
                            
                            # Also directly log to our debug file
                            with open("/tmp/keyboard_debug.log", "a") as f:
                                f.write(f"{timestamp}: KEY LOGGED TO FILE: {key_display}{' with '+mod_list if mod_list else ''}\n")
                                
                        except Exception as e:
                            logger.error(f"Failed to write to key log file: {e}")
                        
                    elif event_type == kCGEventKeyUp:
                        # Get key code and character
                        keycode = CGEventGetIntegerValueField(event, AppKit.kCGKeyboardEventKeycode)
                        
                        # Try to convert keycode to character
                        char = ""
                        try:
                            # Create an NSEvent from the CGEvent to get the characters
                            ns_event = AppKit.NSEvent.eventWithCGEvent_(event)
                            if ns_event:
                                char = ns_event.characters() or ""
                        except Exception:
                            pass
                        
                        # Get current modifier keys state
                        flags = CGEventGetFlags(event)
                        modifiers = self._parse_modifier_flags(flags)
                        
                        # Add key name if available
                        key_name = KEY_CODE_MAP.get(keycode, "")
                        
                        # Record the key release event
                        self._add_event(UIEvent(
                            "key_release",
                            time.time(),
                            keycode=keycode,
                            character=char,
                            key_name=key_name,
                            modifiers=modifiers
                        ))
                        
                        key_display = char or key_name or f"keycode {keycode}"
                        # For key releases, keep at DEBUG level to reduce noise, but add to events
                        logger.debug(f"Key release: {key_display}")
                        
                    elif event_type == kCGEventFlagsChanged:
                        # Get flags value
                        flags = CGEventGetFlags(event)
                        new_modifier_state = self._parse_modifier_flags(flags)
                        
                        # Check which modifier changed
                        changed_modifiers = {}
                        for modifier, state in new_modifier_state.items():
                            if self.modifier_state.get(modifier) != state:
                                changed_modifiers[modifier] = state
                        
                        # Update stored state
                        self.modifier_state = new_modifier_state
                        
                        if changed_modifiers:
                            # Record the modifier change event
                            self._add_event(UIEvent(
                                "modifier_change",
                                time.time(),
                                changes=changed_modifiers,
                                state=new_modifier_state
                            ))
                            
                            # Format a clear message showing which modifiers changed
                            mod_changes = []
                            for mod, state in changed_modifiers.items():
                                mod_changes.append(f"{mod.upper()} {state and 'PRESSED' or 'RELEASED'}")
                            
                            logger.info(f"MODIFIER KEYS: {' | '.join(mod_changes)}")
                    
                    elif event_type == kCGEventScrollWheel:
                        # Get scroll wheel deltas - these are in "line" units
                        delta_y = CGEventGetIntegerValueField(event, kCGScrollWheelEventDeltaAxis1)
                        delta_x = CGEventGetIntegerValueField(event, kCGScrollWheelEventDeltaAxis2)
                        
                        # Get current pointer location
                        location = CGEventGetLocation(event)
                        
                        # Record scroll event
                        if delta_x != 0 or delta_y != 0:
                            self._add_event(UIEvent(
                                "scroll",
                                time.time(),
                                delta_x=delta_x,
                                delta_y=delta_y,
                                position={"x": location.x, "y": location.y}
                            ))
                            
                            logger.info(f"Scroll: dx={delta_x}, dy={delta_y} at {location}")
                    
                except Exception as e:
                    logger.error(f"Error in event_callback: {e}")
                
                # Always return the event to allow it to propagate
                return event
            
            # Convert callback to a C function pointer
            import ctypes
            callback_function = ctypes.CFUNCTYPE(
                ctypes.c_void_p,  # Return type
                ctypes.c_void_p,  # CGEventTapProxy
                ctypes.c_uint32,  # CGEventType
                ctypes.c_void_p,  # CGEventRef
                ctypes.c_void_p   # user_info
            )(event_callback)
            
            # Create the event tap
            logger.error("Creating event tap...")
            try:
                tap = CGEventTapCreate(
                    kCGSessionEventTap,  # Tap at session level
                    kCGHeadInsertEventTap,  # Insert at the beginning of event processing
                    kCGEventTapOptionDefault,  # Default options
                    event_mask,  # Events to listen for
                    callback_function,  # Callback function
                    None  # User data (null in our case)
                )
                
                if tap is None:
                    logger.error("Failed to create event tap. Make sure the app has the required permissions.")
                    # Try to diagnose the issue
                    logger.error("This is likely because:")
                    logger.error("1. The app doesn't have accessibility permissions")
                    logger.error("2. You're running from a sandboxed environment")
                    logger.error("Try running the script directly from Terminal with sudo")
                    # Write to direct debug too
                    with open("/tmp/keyboard_debug.log", "a") as f:
                        f.write("EVENT TAP CREATION FAILED\n")
                    return False
                else:
                    logger.error("Event tap created successfully!")
                    with open("/tmp/keyboard_debug.log", "a") as f:
                        f.write("EVENT TAP CREATED SUCCESSFULLY\n")
            except Exception as e:
                logger.error(f"Exception creating event tap: {e}")
                with open("/tmp/keyboard_debug.log", "a") as f:
                    f.write(f"EVENT TAP CREATION EXCEPTION: {e}\n")
                return False
            
            # Create a run loop source
            runloop_source = CFMachPortCreateRunLoopSource(
                None,
                tap,
                0
            )
            
            # Add source to the current run loop
            CFRunLoopAddSource(
                CFRunLoopGetCurrent(),
                runloop_source,
                kCFRunLoopCommonModes
            )
            
            # Enable the event tap
            CGEventTapEnable(tap, True)
            
            logger.info("Event tap for keyboard and scroll monitoring set up successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error setting up event tap: {e}")
            return False
    
    def _parse_modifier_flags(self, flags):
        """Parse the CGEventFlags into a dictionary of modifier states."""
        # Define the masks for each modifier key
        kCGEventFlagMaskShift = 1 << 17
        kCGEventFlagMaskControl = 1 << 18
        kCGEventFlagMaskAlternate = 1 << 19  # Option key
        kCGEventFlagMaskCommand = 1 << 20
        kCGEventFlagMaskSecondaryFn = 1 << 23
        kCGEventFlagMaskAlphaShift = 1 << 16  # Caps Lock
        
        return {
            "shift": bool(flags & kCGEventFlagMaskShift),
            "control": bool(flags & kCGEventFlagMaskControl),
            "option": bool(flags & kCGEventFlagMaskAlternate),
            "command": bool(flags & kCGEventFlagMaskCommand),
            "fn": bool(flags & kCGEventFlagMaskSecondaryFn),
            "capslock": bool(flags & kCGEventFlagMaskAlphaShift)
        }
    
    def _setup_pynput_keyboard_monitoring(self):
        """Set up keyboard monitoring using pynput library."""
        logger.info("Setting up keyboard monitoring using pynput")
        
        try:
            # Define callback for key press
            def on_press(key):
                if not self.running:
                    return
                
                try:
                    # Get key name or character
                    try:
                        # For normal keys
                        key_char = key.char
                        key_name = key_char
                    except AttributeError:
                        # For special keys
                        key_name = str(key).replace("Key.", "")
                    
                    # Convert pynput modifiers to our format
                    active_mods = []
                    if hasattr(keyboard.Key, 'shift') and key == keyboard.Key.shift:
                        self.modifier_state["shift"] = True
                        active_mods.append("shift")
                    if hasattr(keyboard.Key, 'ctrl') and key == keyboard.Key.ctrl:
                        self.modifier_state["control"] = True
                        active_mods.append("control")
                    if hasattr(keyboard.Key, 'alt') and key == keyboard.Key.alt:
                        self.modifier_state["option"] = True
                        active_mods.append("option")
                    if hasattr(keyboard.Key, 'cmd') and key == keyboard.Key.cmd:
                        self.modifier_state["command"] = True
                        active_mods.append("command")
                        
                    # Get all active modifiers
                    for mod, active in self.modifier_state.items():
                        if active and mod not in active_mods:
                            active_mods.append(mod)
                    
                    # Create a UI event
                    event = UIEvent(
                        "key_press",
                        time.time(),
                        key=key_name,
                        modifiers=self.modifier_state.copy()
                    )
                    
                    # Add the event
                    self._add_event(event)
                    
                    # Direct log to file if set
                    if hasattr(self, 'key_log_file') and self.key_log_file:
                        try:
                            timestamp = time.time()
                            mod_list = '+'.join(active_mods) if active_mods else ""
                            with open(self.key_log_file, 'a') as f:
                                f.write(f"{timestamp},key_press,{key_name},{mod_list}\n")
                        except Exception as e:
                            logger.error(f"Failed to write to key log file: {e}")
                    
                    # Log with high visibility
                    mod_str = ""
                    if active_mods:
                        mod_str = f" with modifiers: {'+'.join(active_mods)}"
                    logger.error(f"KEY PRESS: {key_name}{mod_str}")
                
                except Exception as e:
                    logger.error(f"Error in on_press callback: {e}")
            
            # Define callback for key release
            def on_release(key):
                if not self.running:
                    return
                
                try:
                    # Get key name or character
                    try:
                        key_char = key.char
                        key_name = key_char
                    except AttributeError:
                        key_name = str(key).replace("Key.", "")
                    
                    # Update modifier state
                    if hasattr(keyboard.Key, 'shift') and key == keyboard.Key.shift:
                        self.modifier_state["shift"] = False
                    if hasattr(keyboard.Key, 'ctrl') and key == keyboard.Key.ctrl:
                        self.modifier_state["control"] = False
                    if hasattr(keyboard.Key, 'alt') and key == keyboard.Key.alt:
                        self.modifier_state["option"] = False
                    if hasattr(keyboard.Key, 'cmd') and key == keyboard.Key.cmd:
                        self.modifier_state["command"] = False
                    
                    # Create a UI event
                    event = UIEvent(
                        "key_release",
                        time.time(),
                        key=key_name,
                        modifiers=self.modifier_state.copy()
                    )
                    
                    # Add the event
                    self._add_event(event)
                    
                    # Direct log to file if set
                    if hasattr(self, 'key_log_file') and self.key_log_file:
                        try:
                            with open(self.key_log_file, 'a') as f:
                                f.write(f"{time.time()},key_release,{key_name}\n")
                        except Exception as e:
                            logger.error(f"Failed to write to key log file: {e}")
                    
                    # Log at debug level to reduce noise
                    logger.debug(f"KEY RELEASE: {key_name}")
                
                except Exception as e:
                    logger.error(f"Error in on_release callback: {e}")
            
            # Create and start the listener
            self.keyboard_listener = keyboard.Listener(
                on_press=on_press,
                on_release=on_release
            )
            self.keyboard_listener.daemon = True
            self.keyboard_listener.start()
            
            logger.info("Keyboard monitoring started successfully using pynput")
            return True
            
        except Exception as e:
            logger.error(f"Failed to set up keyboard monitoring: {e}")
            return False
    
    def _keyboard_event_loop(self):
        """Legacy method - kept for compatibility but no longer used."""
        logger.error("Legacy keyboard event loop method called, but we're using pynput now")
        
        # Just keep the thread alive
        while self.running:
            time.sleep(1)
    
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
        
        # Set up mouse and keyboard event listeners
        self._setup_mouse_tracking()
        
        # Set up keyboard monitoring using pynput (more reliable than CGEventTap)
        logger.info("Setting up keyboard monitoring...")
        
        # Try the pynput-based monitor first (should work in all cases)
        if self._setup_pynput_keyboard_monitoring():
            logger.info("Keyboard monitoring set up using pynput")
            
            # Write a debug log to confirm
            try:
                with open("/tmp/keyboard_debug.log", "w") as f:
                    f.write(f"{time.time()}: Keyboard monitoring started using pynput\n")
            except:
                pass
        else:
            # Fall back to the old method if pynput fails for some reason
            logger.error("Failed to set up keyboard monitoring with pynput, trying CGEventTap...")
            
            # Try the old event tap method as fallback
            if self._setup_event_tap():
                logger.error("Event tap setup successful, starting keyboard thread...")
                self.keyboard_thread = threading.Thread(target=self._keyboard_event_loop)
                self.keyboard_thread.daemon = True
                self.keyboard_thread.start()
            else:
                logger.error("All keyboard monitoring methods failed!")
                logger.error("Make sure the script has accessibility permissions")
                logger.error("Go to System Preferences > Security & Privacy > Privacy > Accessibility")
                logger.error("and add Terminal or your Python app to the list")
                try:
                    with open("/tmp/keyboard_debug.log", "a") as f:
                        f.write(f"{time.time()}: ALL keyboard monitoring methods failed!\n")
                except:
                    pass
        
        # Start text selection monitoring if enabled
        if self.monitor_text_selection:
            logger.info("Setting up text selection monitoring...")
            self.selection_thread = threading.Thread(target=self._selection_monitoring_loop)
            self.selection_thread.daemon = True
            self.selection_thread.start()
            logger.info(f"Text selection monitoring started (polling every {self.selection_interval:.1f}s)")
        else:
            logger.debug("Text selection monitoring disabled")
        
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
        
        # Stop the keyboard listener if we're using pynput
        if hasattr(self, 'keyboard_listener') and self.keyboard_listener:
            try:
                self.keyboard_listener.stop()
                logger.info("Keyboard listener stopped")
            except Exception as e:
                logger.error(f"Error stopping keyboard listener: {e}")
        
        # The old keyboard thread can't be cleanly stopped because it's running a CFRunLoop
        # We'll just let it terminate when the process exits
        
        # Close the timeline JSON file if it's open and in JSON format
        if hasattr(self, 'timeline_file') and self.timeline_file and hasattr(self, 'timeline_format') and self.timeline_format == 'json':
            try:
                with open(self.timeline_file, 'a') as f:
                    f.write('\n]\n')  # Close the JSON array
                logger.info(f"Timeline written to {self.timeline_file}")
            except Exception as e:
                logger.error(f"Error closing timeline file: {e}")
        
        logger.info("MacOS UI Monitor stopped")
    
    def _setup_mouse_tracking(self):
        """Set up simplified mouse tracking using a separate thread."""
        def track_mouse():
            prev_position = None
            prev_click_time = 0
            
            while self.running:
                try:
                    # Get current mouse position
                    mouse_loc = AppKit.NSEvent.mouseLocation()
                    pos = (mouse_loc.x, AppKit.NSScreen.mainScreen().frame().size.height - mouse_loc.y)
                    
                    # Update stored position
                    self.mouse_position = pos
                    
                    # Check for significant movement
                    if prev_position is None or ((abs(pos[0] - prev_position[0]) > 5) or 
                                                (abs(pos[1] - prev_position[1]) > 5)):
                        prev_position = pos
                        
                        # We could add mouse move events if needed
                        # self._add_event(UIEvent("mouse_move", time.time(), 
                        #                         position={"x": pos[0], "y": pos[1]}))
                    
                    # Check for mouse buttons using NSEvent's pressedMouseButtons
                    buttons = AppKit.NSEvent.pressedMouseButtons()
                    
                    # Left button = bit 0, right button = bit 1
                    left_pressed = (buttons & 1) != 0
                    right_pressed = (buttons & 2) != 0
                    
                    # To avoid duplicate click events, add a small timeout
                    current_time = time.time()
                    if (left_pressed or right_pressed) and (current_time - prev_click_time) > 0.1:
                        button = "right" if right_pressed else "left"
                        self.last_click_position = self.mouse_position
                        
                        # Try to determine what was clicked on
                        element_at_position = self._get_element_at_position(self.mouse_position)
                        
                        if element_at_position:
                            self.last_click_element = element_at_position
                            element_info = ElementInfo(element_at_position)
                            
                            # Add click event
                            self._add_event(UIEvent(
                                "click",
                                time.time(),
                                button=button,
                                position={"x": self.mouse_position[0], "y": self.mouse_position[1]},
                                element=element_info.to_dict()
                            ))
                            
                            # Log with more compact representation to avoid truncation
                            title_str = f'"{element_info.title}"' if element_info.title else "No title"
                            logger.info(f"{button.title()} click at {self.mouse_position} on {title_str} ({element_info.role})")
                            
                            # When clicking, force refresh of active app data to catch transitions
                            # Give a small delay to allow app to activate
                            threading.Timer(0.5, self._update_ui_state).start()
                            
                        else:
                            # Click without a determined element
                            self._add_event(UIEvent(
                                "click",
                                time.time(),
                                button=button,
                                position={"x": self.mouse_position[0], "y": self.mouse_position[1]},
                                element=None
                            ))
                            
                            logger.info(f"{button.title()} click at {self.mouse_position}")
                            # Still trigger a UI update after click
                            threading.Timer(0.5, self._update_ui_state).start()
                        
                        prev_click_time = current_time
                    
                except Exception as e:
                    logger.error(f"Error tracking mouse: {e}")
                
                # Polling interval for mouse
                time.sleep(0.05)
        
        # Start the mouse tracking thread
        mouse_thread = threading.Thread(target=track_mouse)
        mouse_thread.daemon = True
        mouse_thread.start()
    
    def _selection_monitoring_loop(self):
        """Background thread that monitors text selections."""
        logger.info("Text selection monitoring thread started")
        last_selection_time = 0
        
        while self.running:
            try:
                # Don't check too frequently
                time.sleep(self.selection_interval)
                
                # Check if enough time has passed since the last selection event
                now = time.time()
                if now - last_selection_time < self.selection_change_threshold:
                    continue
                    
                # Get current selection
                selection, source = self.get_text_selection()
                
                # If no selection or same as last selection, continue
                if not selection or selection == self.last_selection:
                    continue
                    
                # Limit selection size for logging
                display_selection = selection
                if len(display_selection) > 200:
                    display_selection = display_selection[:197] + "..."
                
                # Create a selection event
                event = UIEvent(
                    "text_selection",
                    now,
                    text=selection,
                    source=source,
                    app_name=self.current_app.element.get_title() if self.current_app else "Unknown"
                )
                
                # Add the event
                self._add_event(event)
                
                # Update tracking variables
                self.last_selection = selection
                last_selection_time = now
                
                # Log the selection
                logger.info(f"Text selection: {display_selection} [from {source}]")
                
            except Exception as e:
                logger.debug(f"Error checking selection: {e}")
    
    def _polling_loop(self):
        """Background thread that polls the UI state regularly."""
        logger.info("Polling thread started")
        while self.running:
            try:
                self._update_ui_state()
            except Exception as e:
                logger.error(f"Error updating UI state: {e}")
            
            time.sleep(self.polling_interval)
    
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
    
    def _get_element_at_position(self, position):
        """Try to find the UI element at the given screen position."""
        try:
            # Try to use AXUIElementCopyElementAtPosition
            from ApplicationServices import AXUIElementCopyElementAtPosition
            
            system_wide = self.system_wide.element
            result, element = AXUIElementCopyElementAtPosition(system_wide, position[0], position[1], None)
            
            if element:
                return MacOSUIElement(ThreadSafeAXUIElement(element))
            
            # If that fails, try asking the system-wide element for the element at position
            params = {"x": position[0], "y": position[1]}
            element = self.system_wide.get_attribute("AXElementAtPosition", params)
            if element:
                return MacOSUIElement(ThreadSafeAXUIElement(element))
            
            return None
        except Exception as e:
            logger.error(f"Error getting element at position: {e}")
            return None
    
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
    
    def get_clipboard_text(self):
        """Get text from the system clipboard."""
        try:
            # Use pbpaste command to get clipboard contents
            result = subprocess.run(['pbpaste'], capture_output=True, text=True, timeout=0.5)
            if result.returncode == 0:
                return result.stdout.strip()
            else:
                return None
        except Exception as e:
            logger.debug(f"Error accessing clipboard: {e}")
            return None
    
    def get_selected_text(self):
        """Get selected text from the focused element using accessibility API."""
        try:
            if self.current_element:
                # Try to get selected text directly
                selected_text = self.current_element.element.get_attribute("AXSelectedText")
                if selected_text:
                    return clean_accessibility_value(selected_text)
                
                # If no selected text but value exists, try to determine selection from value
                value = self.current_element.element.get_attribute("AXValue")
                selected_range = self.current_element.element.get_attribute("AXSelectedTextRange")
                
                if value and selected_range and isinstance(selected_range, dict):
                    # Extract selection bounds
                    location = selected_range.get("location", 0)
                    length = selected_range.get("length", 0)
                    
                    if length > 0 and isinstance(value, str):
                        # Extract the substring
                        try:
                            return value[location:location+length]
                        except:
                            pass
            return None
        except Exception as e:
            logger.debug(f"Error getting selected text: {e}")
            return None
            
    def get_text_selection(self):
        """
        Try multiple methods to get the currently selected text.
        Returns a tuple of (selected_text, source_method)
        """
        # Try accessibility API first
        selected_text = self.get_selected_text()
        if selected_text:
            return selected_text, "accessibility"
            
        # Try clipboard as fallback
        clipboard_text = self.get_clipboard_text()
        if clipboard_text:
            return clipboard_text, "clipboard"
            
        return None, None


def setup_argparse():
    """Set up command line argument parsing."""
    parser = argparse.ArgumentParser(
        description="macOS UI Monitor - Track UI state, events, and interactions",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    parser.add_argument(
        "--polling-interval", 
        type=float, 
        default=0.2,
        help="Interval in seconds between UI state polls"
    )
    
    parser.add_argument(
        "--history-size", 
        type=int, 
        default=1000,
        help="Maximum number of events to keep in history"
    )
    
    parser.add_argument(
        "--debug", 
        action="store_true", 
        help="Enable debug logging"
    )
    
    parser.add_argument(
        "--quiet", 
        action="store_true", 
        help="Reduce logging to warnings and errors only"
    )
    
    parser.add_argument(
        "--output-file", 
        type=str,
        help="Path to file where events should be saved as JSON lines"
    )
    
    parser.add_argument(
        "--verbose", 
        action="store_true",
        help="Show detailed app state information"
    )
    
    parser.add_argument(
        "--screenshots", 
        action="store_true",
        default=True,  # Enable by default
        help="Take screenshots on click events (enabled by default)"
    )
    
    parser.add_argument(
        "--screenshot-dir", 
        type=str,
        default="./screenshots",
        help="Directory to save screenshots in"
    )
    
    parser.add_argument(
        "--dump-attributes", 
        action="store_true",
        help="Dump all raw accessibility attributes for debugging"
    )
    
    parser.add_argument(
        "--log-events", 
        choices=["all", "clicks", "keys", "scroll", "modifiers", "selections"],
        nargs="+",
        default=["all"],
        help="Specify which events to log (default: all)"
    )
    
    parser.add_argument(
        "--log-file", 
        type=str,
        help="Path to a log file where all events will be saved (separate from output file)"
    )
    
    parser.add_argument(
        "--key-log-file", 
        type=str,
        help="Path to a simplified CSV log file that will contain ONLY keyboard events"
    )
    
    parser.add_argument(
        "--timeline-file",
        type=str,
        default="./timeline.json",
        help="Path to a consolidated timeline file containing all events in chronological order (default: ./timeline.json)"
    )
    
    parser.add_argument(
        "--timeline-format",
        choices=["json", "csv"],
        default="json",
        help="Format for the timeline file (default: json)"
    )
    
    parser.add_argument(
        "--fallback-keyboard-logging",
        action="store_true",
        help="Use fallback terminal-based keyboard logging method if the main method fails"
    )
    
    parser.add_argument(
        "--monitor-text-selection",
        action="store_true",
        default=True,  # Enable by default
        help="Monitor and log text selections in applications (enabled by default)"
    )
    
    parser.add_argument(
        "--selection-interval", 
        type=float, 
        default=1.0,
        help="Interval in seconds between checking for text selections"
    )
    
    parser.add_argument(
        "--log-file-size", 
        type=int,
        default=10485760,  # 10MB
        help="Maximum size of log file in bytes before rotation"
    )
    
    parser.add_argument(
        "--log-file-backups", 
        type=int,
        default=3,
        help="Number of log file backups to keep when rotating"
    )
    
    # Register completions if argcomplete is installed
    try:
        import argcomplete
        argcomplete.autocomplete(parser)
    except ImportError:
        pass
    
    return parser


def fallback_keyboard_logging():
    """
    A fallback method to log keystrokes if the event tap doesn't work.
    This uses a subprocess with the 'script' command to record all terminal input.
    """
    import subprocess
    import sys
    import os
    
    # Create a debug output
    with open("/tmp/keyboard_debug.log", "a") as f:
        f.write(f"{time.time()}: Starting fallback keyboard logging\n")
    
    # Check if we're already in a logged session
    if os.environ.get('SCRIPT_LOGGING_ACTIVE'):
        print("Already in a script logging session, not starting another one.")
        return
    
    # Create a directory for logs
    os.makedirs("/tmp/keystroke_logs", exist_ok=True)
    
    # File for logging
    log_file = f"/tmp/keystroke_logs/keylog_{time.strftime('%Y%m%d_%H%M%S')}.log"
    
    print(f"Starting fallback keyboard logger. Your keystrokes will be logged to: {log_file}")
    print("This is necessary because the main keyboard monitoring method failed.")
    print("Type 'exit' to stop recording and quit.")
    
    # Set environment variable to prevent recursion
    new_env = os.environ.copy()
    new_env['SCRIPT_LOGGING_ACTIVE'] = '1'
    
    # Use script command to record all terminal input
    try:
        subprocess.call(['script', '-a', log_file], env=new_env)
    except KeyboardInterrupt:
        print("Keyboard logging stopped.")
    
    print(f"Keystroke log saved to: {log_file}")
    sys.exit(0)


def main(argv=None):
    """Main entry point for the UI monitor."""
    parser = setup_argparse()
    args = parser.parse_args(argv)
    
    # Set up logging - we need at least INFO level to see events
    log_level = logging.DEBUG if args.debug else (logging.WARNING if args.quiet else logging.INFO)
    
    # First reset root handlers in case basicConfig was called elsewhere
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Create a custom formatter
    log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # Configure root logger first with base level
    root_logger.setLevel(logging.DEBUG)  # Allow everything through at root level
    
    # Set up console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)
    console_handler.setLevel(log_level)
    root_logger.addHandler(console_handler)
    
    # Set up file handler if log file is specified
    if args.log_file:
        # Create log directory if it doesn't exist
        log_dir = os.path.dirname(os.path.abspath(args.log_file))
        os.makedirs(log_dir, exist_ok=True)
        
        # Create a rotating file handler
        file_handler = RotatingFileHandler(
            args.log_file, 
            maxBytes=args.log_file_size, 
            backupCount=args.log_file_backups,
            encoding='utf-8'
        )
        file_handler.setFormatter(log_formatter)
        # Always log at INFO level to file to ensure we capture keyboard events
        file_handler.setLevel(logging.INFO)
        root_logger.addHandler(file_handler)
        
        print(f"Logging events to file: {os.path.abspath(args.log_file)}")
    
    # Make sure our module logger is at least INFO level so events show up
    logger.setLevel(logging.INFO if not args.quiet else log_level)
    print(f"Module logger level: {logging.getLevelName(logger.level)}")
    print(f"Root logger level: {logging.getLevelName(root_logger.level)}")
    
    # Create output file directory if it doesn't exist
    if args.output_file:
        os.makedirs(os.path.dirname(os.path.abspath(args.output_file)), exist_ok=True)
    
    # Create screenshot directory if screenshots enabled
    screenshot_dir = None
    if args.screenshots:
        screenshot_dir = args.screenshot_dir
        
    # If dump-attributes is enabled, set global flag for ElementInfo
    if args.dump_attributes:
        # Monkeypatch the ElementInfo.to_dict method to include raw attributes
        original_to_dict = ElementInfo.to_dict
        
        def to_dict_with_raw_attrs(self):
            result = original_to_dict(self)
            # Add raw attributes
            result["_raw_attributes"] = {
                k: str(v) for k, v in self.raw_attributes.items()
            }
            return result
            
        ElementInfo.to_dict = to_dict_with_raw_attrs
        logger.info("Raw accessibility attributes will be included in element info")
    
    # Create a monitor to check if keyboard event tap will work
    event_tap_file = "/tmp/keyboard_debug.log"
    if os.path.exists(event_tap_file):
        os.remove(event_tap_file)
        
    # Create and start the monitor
    monitor = MacOSUIMonitor(
        history_size=args.history_size,
        polling_interval=args.polling_interval,
        log_level=log_level,
        output_file=args.output_file,
        screenshot_dir=screenshot_dir,
        take_screenshots=args.screenshots,
        key_log_file=args.key_log_file,
        timeline_file=args.timeline_file,
        timeline_format=args.timeline_format,
        monitor_text_selection=args.monitor_text_selection,
        selection_interval=args.selection_interval
    )
    
    # Check if fallback is needed after a brief delay to let event tap start
    if args.fallback_keyboard_logging:
        time.sleep(3)  # Wait for event tap to initialize
        
        # Check if keyboard events are being detected
        keyboard_working = False
        
        # Check if the debug file exists and contains evidence of working keyboard monitoring
        if os.path.exists(event_tap_file):
            with open(event_tap_file, "r") as f:
                content = f.read()
                if "Test event posted" in content and "EVENT TAP CREATED SUCCESSFULLY" in content:
                    keyboard_working = True
        
        if not keyboard_working:
            print("\n\n============================================================")
            print("WARNING: Keyboard event monitoring does not appear to be working")
            print("============================================================")
            print("This is likely because:")
            print("1. The app doesn't have proper accessibility permissions")
            print("2. You're running in a sandboxed environment that restricts access")
            print("\nStarting fallback keyboard logging method...\n")
            
            # Stop the monitor before switching to fallback
            monitor.stop()
            # Switch to fallback method
            fallback_keyboard_logging()
            return 1  # Exit with code 1
    
    # Example callback for click events
    def on_click(event):
        details = []
        
        if "button" in event.details:
            details.append(f"Button: {event.details['button']}")
        
        if "position" in event.details:
            pos = event.details["position"]
            details.append(f"Position: ({pos['x']:.1f}, {pos['y']:.1f})")
        
        if "element" in event.details:
            element = event.details["element"]
            # Get the most important element info
            element_info = []
            
            if "title" in element and element["title"]:
                element_info.append(f'"{element["title"]}"')
                
            if "role" in element:
                if "role_description" in element:
                    element_info.append(element["role_description"])
                else:
                    element_info.append(element["role"])
                    
            if "subrole" in element:
                element_info.append(f"subrole:{element['subrole']}")
                
            if "status" in element:
                status = element["status"]
                if status.get("selected"):
                    element_info.append("selected")
                if status.get("focused"):
                    element_info.append("focused")
            
            if element_info:
                details.append(f"Element: {' '.join(element_info)}")
        
        if "screenshot" in event.details:
            details.append(f"Screenshot: {os.path.basename(event.details['screenshot'])}")
        
        # Print the basic details first
        if details:
            print(f"Click detected: {', '.join(details)}")
        
        # If debug mode or dump attributes is enabled, print raw attributes
        if args.debug or args.dump_attributes:
            if "element" in event.details and "_raw_attributes" in event.details["element"]:
                print("\nAccessibility Attributes:")
                raw_attrs = event.details["element"]["_raw_attributes"]
                for key in sorted(raw_attrs.keys()):
                    value = raw_attrs[key]
                    # For long values, truncate them
                    if len(str(value)) > 50:
                        value = f"{str(value)[:47]}..."
                    print(f"  {key}: {value}")
    
    # Example callback for keyboard events
    def on_key_press(event):
        details = []
        
        # First try character, then key_name, then keycode
        if "character" in event.details and event.details["character"]:
            details.append(f"Key: '{event.details['character']}'")
        elif "key_name" in event.details and event.details["key_name"]:
            details.append(f"Key: {event.details['key_name']}")
        elif "keycode" in event.details:
            details.append(f"Keycode: {event.details['keycode']}")
            
        if "modifiers" in event.details:
            mods = event.details["modifiers"]
            active_mods = [name for name, active in mods.items() if active]
            if active_mods:
                details.append(f"Modifiers: {'+'.join(active_mods)}")
        
        if details:
            print(f"Key press: {', '.join(details)}")
            
    # Example callback for key release events
    def on_key_release(event):
        if args.debug:  # Only show releases in debug mode to reduce verbosity
            # First try character, then key_name, then keycode
            if "character" in event.details and event.details["character"]:
                print(f"Key release: '{event.details['character']}'")
            elif "key_name" in event.details and event.details["key_name"]:
                print(f"Key release: {event.details['key_name']}")
            elif "keycode" in event.details:
                print(f"Key release: keycode {event.details['keycode']}")
    
    # Example callback for modifier key changes
    def on_modifier_change(event):
        if "changes" in event.details:
            changes = event.details["changes"]
            mod_changes = []
            for mod, state in changes.items():
                mod_changes.append(f"{mod} {'pressed' if state else 'released'}")
            
            if mod_changes:
                print(f"Modifier keys: {', '.join(mod_changes)}")
    
    # Example callback for scroll events
    def on_scroll(event):
        details = []
        
        if "delta_x" in event.details and event.details["delta_x"] != 0:
            details.append(f"Horizontal: {event.details['delta_x']}")
            
        if "delta_y" in event.details and event.details["delta_y"] != 0:
            details.append(f"Vertical: {event.details['delta_y']}")
            
        if "position" in event.details:
            pos = event.details["position"]
            details.append(f"Position: ({pos['x']:.1f}, {pos['y']:.1f})")
            
        if details:
            print(f"Scroll: {', '.join(details)}")
            
    # Example callback for text selection events
    def on_text_selection(event):
        if "text" in event.details:
            text = event.details["text"]
            source = event.details.get("source", "unknown")
            app_name = event.details.get("app_name", "Unknown App")
            
            # Truncate text for display if too long
            if len(text) > 100:
                display_text = text[:97] + "..."
            else:
                display_text = text
                
            print(f"Text Selected in {app_name}: \"{display_text}\"")
            
            # Print metadata if in verbose mode
            if args.verbose:
                print(f"  Source: {source}")
                print(f"  Length: {len(text)} characters")
    
    # Register callbacks based on log events selection
    log_events = args.log_events
    
    # If "all" is in the list, include all events
    if "all" in log_events:
        log_events = ["clicks", "keys", "modifiers", "scroll", "selections"]
    
    # Register appropriate callbacks
    if "clicks" in log_events:
        monitor.add_callback("click", on_click)
        
    if "keys" in log_events:
        monitor.add_callback("key_press", on_key_press)
        monitor.add_callback("key_release", on_key_release)
        
    if "modifiers" in log_events:
        monitor.add_callback("modifier_change", on_modifier_change)
        
    if "scroll" in log_events:
        monitor.add_callback("scroll", on_scroll)
        
    if "selections" in log_events:
        monitor.add_callback("text_selection", on_text_selection)
    
    try:
        # Start monitoring
        monitor.start()
        print("UI Monitor running. Press Ctrl+C to stop.")
        
        # Show information about enabled features
        print("\nEnabled features:")
        if "clicks" in log_events:
            print("- Click events will be logged")
        if "keys" in log_events:
            print("- Keyboard events will be logged")
        if "modifiers" in log_events:
            print("- Modifier key events will be logged")
        if "scroll" in log_events:
            print("- Scroll events will be logged")
        if "selections" in log_events:
            print(f"- Text selections will be logged (checking every {args.selection_interval:.1f}s)")
        
        # Screenshots are enabled by default now
        print(f"- Screenshots will be saved to: {os.path.abspath(args.screenshot_dir)}")
        if args.log_file:
            print(f"- All events will be saved to log file: {os.path.abspath(args.log_file)}")
            print("  (This file will contain complete keyboard event logs)")
        if args.key_log_file:
            print(f"- Keyboard events will be saved to CSV file: {os.path.abspath(args.key_log_file)}")
            print("  (This is a simpler format that is guaranteed to capture all keystrokes)")
        
        # Always show timeline file info since it's now default
        print(f"- Consolidated timeline will be saved as {args.timeline_format.upper()} to: {os.path.abspath(args.timeline_file)}")
        print("  (This file will contain all events in chronological order with context)")
        
        if args.output_file:
            print(f"- Raw events will be saved as JSON lines to: {os.path.abspath(args.output_file)}")
        
        # Keep the main thread alive
        while True:
            time.sleep(1)
            
            # Periodically print current state
            if monitor.running:
                current_state = monitor.get_current_state()
                app_name = current_state.get("current_app", {}).get("name", "None")
                app_method = current_state.get("current_app", {}).get("method", "Unknown")
                window_title = current_state.get("current_window", {}).get("title", "None")
                mouse_pos = current_state.get("mouse_position", {})
                
                if args.verbose:
                    print(f"App: {app_name} ({app_method}) | Window: {window_title} | Mouse: {mouse_pos}")
                else:
                    print(f"App: {app_name} | Window: {window_title}")
    
    except KeyboardInterrupt:
        print("Stopping UI Monitor...")
    finally:
        monitor.stop()
    
    return 0  # Return success exit code


if __name__ == "__main__":
    main()
