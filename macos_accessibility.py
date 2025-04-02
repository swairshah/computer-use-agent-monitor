"""
macOS Accessibility module for MCP server.
This module provides functionality to interact with the macOS Accessibility APIs.
"""

import time
import hashlib
import logging
from typing import Dict, List, Optional, Tuple, Any, Set

import AppKit
from ApplicationServices import (
    AXUIElementCreateSystemWide,
    AXUIElementCreateApplication,
    AXUIElementCopyAttributeNames,
    AXUIElementCopyAttributeValue,
    AXUIElementPerformAction,
    AXUIElementSetAttributeValue,
    AXUIElementGetPid,
    AXValueGetValue,
    kAXErrorSuccess,
    kAXValueCGPointType,
    kAXValueCGSizeType
)
from Quartz import (
    CGEventSourceCreate,
    CGEventCreateMouseEvent,
    CGEventCreateKeyboardEvent,
    CGEventSetFlags,
    CGEventPost,
    CGPointMake,
    kCGEventSourceStateHIDSystemState,
    kCGEventMouseMoved,
    kCGEventLeftMouseDown,
    kCGEventLeftMouseUp,
    kCGEventRightMouseDown,
    kCGEventRightMouseUp,
    kCGHIDEventTap,
    kCGMouseButtonLeft,
    kCGMouseButtonRight
)
from CoreFoundation import (
    CFArrayGetCount,
    CFArrayGetValueAtIndex,
    CFCopyDescription,
    CFGetTypeID,
    CFArrayGetTypeID
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants for key codes
KEY_RETURN = 36
KEY_TAB = 48
KEY_SPACE = 49
KEY_DELETE = 51
KEY_ESCAPE = 53
KEY_ARROW_LEFT = 123
KEY_ARROW_RIGHT = 124
KEY_ARROW_DOWN = 125
KEY_ARROW_UP = 126

# Constants for modifier keys
MODIFIER_COMMAND = 1 << 20  # NSEventModifierFlagCommand
MODIFIER_SHIFT = 1 << 17    # NSEventModifierFlagShift
MODIFIER_OPTION = 1 << 19   # NSEventModifierFlagOption
MODIFIER_CONTROL = 1 << 18  # NSEventModifierFlagControl
MODIFIER_FN = 1 << 23       # NSEventModifierFlagFunction

class ThreadSafeAXUIElement:
    """Thread-safe wrapper for AXUIElement."""
    
    def __init__(self, ax_ui_element):
        """Initialize with an AXUIElement object."""
        self.element = ax_ui_element
    
    @classmethod
    def system_wide(cls):
        """Create a system-wide accessibility element."""
        return cls(AXUIElementCreateSystemWide())
    
    @classmethod
    def application(cls, pid):
        """Create an accessibility element for a specific application."""
        return cls(AXUIElementCreateApplication(pid))
    
    def get_attribute_names(self):
        """Get list of attribute names supported by the element."""
        names = AXUIElementCopyAttributeNames(self.element, None)
        if names:
            return names
        return []
    
    def get_attribute(self, attribute_name):
        """Get an attribute value from the element."""
        value = AXUIElementCopyAttributeValue(self.element, attribute_name, None)
        if value is not None:
            return value
        return None
    
    def perform_action(self, action_name):
        """Perform an action on the element."""
        return AXUIElementPerformAction(self.element, action_name) == kAXErrorSuccess
    
    def set_attribute(self, attribute_name, value):
        """Set an attribute value for the element."""
        return AXUIElementSetAttributeValue(self.element, attribute_name, value) == kAXErrorSuccess
    
    def get_role(self):
        """Get the role of the element."""
        value = self.get_attribute("AXRole")
        if value:
            return CFCopyDescription(value)
        return None
    
    def get_title(self):
        """Get the title of the element."""
        value = self.get_attribute("AXTitle")
        if value:
            return CFCopyDescription(value)
        return None
    
    def get_children(self):
        """Get child elements."""
        children_value = self.get_attribute("AXChildren")
        if not children_value:
            return []
        
        count = CFArrayGetCount(children_value)
        children = []
        
        for i in range(count):
            child_element = CFArrayGetValueAtIndex(children_value, i)
            children.append(ThreadSafeAXUIElement(child_element))
        
        return children
    
    def get_windows(self):
        """Get window elements."""
        windows_value = self.get_attribute("AXWindows")
        if not windows_value:
            return []
        
        count = CFArrayGetCount(windows_value)
        windows = []
        
        for i in range(count):
            window_element = CFArrayGetValueAtIndex(windows_value, i)
            windows.append(ThreadSafeAXUIElement(window_element))
        
        return windows
    
    def get_position(self):
        """Get the element's position."""
        try:
            position = self.get_attribute("AXPosition")
            if not position:
                logger.debug("No AXPosition attribute found")
                return (0, 0)
            
            # For PyObjC, we can use NSValue methods directly
            # This is more reliable than using AXValueGetValue
            if hasattr(position, 'pointValue'):
                point = position.pointValue()
                return (point.x, point.y)
            
            # Fallback for other cases
            logger.debug("Using string parsing fallback for position")
            pos_str = CFCopyDescription(position)
            
            # Special handling for error codes
            if isinstance(pos_str, tuple) and len(pos_str) >= 1 and pos_str[0] == "-25204":
                # -25204 is AXErrorFailure - attribute not supported
                logger.debug("Element doesn't support position attribute (AXErrorFailure)")
                return (0, 0)
                
            if pos_str and isinstance(pos_str, str):
                if "x=" in pos_str and "y=" in pos_str:
                    # Parse from string like "x=100 y=200"
                    try:
                        x_part = pos_str.split("x=")[1].split()[0]
                        y_part = pos_str.split("y=")[1].split()[0]
                        return (float(x_part), float(y_part))
                    except (ValueError, IndexError) as e:
                        logger.debug(f"Failed to parse position string: {e}")
                
            # Only log a warning at debug level to avoid spamming logs
            logger.debug(f"Could not extract position from {pos_str}")
            return (0, 0)
        except Exception as e:
            logger.warning(f"Error getting position: {e}")
            return (0, 0)
    
    def get_size(self):
        """Get the element's size."""
        try:
            size = self.get_attribute("AXSize")
            if not size:
                logger.debug("No AXSize attribute found")
                return (0, 0)
            
            # For PyObjC, we can use NSValue methods directly
            if hasattr(size, 'sizeValue'):
                size_val = size.sizeValue()
                return (size_val.width, size_val.height)
            
            # Fallback for other cases
            logger.debug("Using string parsing fallback for size")
            size_str = CFCopyDescription(size)
            
            # Special handling for error codes
            if isinstance(size_str, tuple) and len(size_str) >= 1 and size_str[0] == "-25204":
                # -25204 is AXErrorFailure - attribute not supported
                logger.debug("Element doesn't support size attribute (AXErrorFailure)")
                return (0, 0)
                
            if size_str and isinstance(size_str, str):
                if "w=" in size_str and "h=" in size_str:
                    # Parse from string like "w=100 h=200"
                    try:
                        w_part = size_str.split("w=")[1].split()[0]
                        h_part = size_str.split("h=")[1].split()[0]
                        return (float(w_part), float(h_part))
                    except (ValueError, IndexError) as e:
                        logger.debug(f"Failed to parse size string: {e}")
                
            # Only log a warning at debug level to avoid spamming logs
            logger.debug(f"Could not extract size from {size_str}")
            return (0, 0)
        except Exception as e:
            logger.warning(f"Error getting size: {e}")
            return (0, 0)


class MacOSUIElement:
    """MacOS UI Element implementation."""
    
    def __init__(self, element, use_background_apps=False, activate_app=True):
        """Initialize with a ThreadSafeAXUIElement."""
        self.element = element
        self.use_background_apps = use_background_apps
        self.activate_app = activate_app
    
    def object_id(self):
        """Generate a stable object ID for this element."""
        # Collect stable attributes
        role = self.element.get_role() or ""
        title = self.element.get_title() or ""
        
        # Get position and size
        x, y = self.element.get_position()
        width, height = self.element.get_size()
        
        # Count children
        children = self.element.get_children()
        count_of_children = len(children)
        
        # Create a hash from combined attributes
        hash_input = f"{role}{title}{width}{height}{count_of_children}"
        return int(hashlib.md5(hash_input.encode()).hexdigest(), 16) % (2**64)
    
    def id(self):
        """Get a string ID."""
        return str(self.object_id())
    
    def role(self):
        """Get the role of the element, mapped to a generic role."""
        role = self.element.get_role() or ""
        return self._macos_role_to_generic_role(role)
    
    def attributes(self):
        """Get all attributes of the element."""
        attributes = {
            "role": self.role(),
            "label": self.element.get_title(),
            "value": None,
            "description": None,
            "properties": {}
        }
        
        # Get position and size for properties
        try:
            x, y = self.element.get_position()
            width, height = self.element.get_size()
            attributes["properties"]["position"] = {"x": x, "y": y}
            attributes["properties"]["size"] = {"width": width, "height": height}
        except Exception as e:
            logger.warning(f"Could not get position/size: {e}")
        
        # Get description
        desc_value = self.element.get_attribute("AXDescription")
        if desc_value:
            attributes["description"] = CFCopyDescription(desc_value)
        
        # Get value
        value = self.element.get_attribute("AXValue")
        if value:
            attributes["value"] = CFCopyDescription(value)
        
        return attributes
    
    def children(self):
        """Get child elements."""
        all_children = []
        
        # First try to get windows
        windows = self.element.get_windows()
        for window in windows:
            all_children.append(MacOSUIElement(window, 
                                               self.use_background_apps, 
                                               self.activate_app))
        
        # Then get regular children
        children = self.element.get_children()
        for child in children:
            all_children.append(MacOSUIElement(child, 
                                               self.use_background_apps, 
                                               self.activate_app))
        
        return all_children
    
    def parent(self):
        """Get parent element."""
        parent_element = self.element.get_attribute("AXParent")
        if parent_element:
            return MacOSUIElement(ThreadSafeAXUIElement(parent_element), 
                                 self.use_background_apps, 
                                 self.activate_app)
        return None
    
    def bounds(self):
        """Get element bounds (x, y, width, height)."""
        try:
            x, y = self.element.get_position()
            width, height = self.element.get_size()
            return (x, y, width, height)
        except Exception as e:
            logger.warning(f"Could not get bounds: {e}")
            return (0, 0, 0, 0)
    
    def click(self):
        """Click the element."""
        # Try AXPress action first
        if self._click_press():
            return {
                "method": "AXPress",
                "coordinates": None,
                "details": "Used accessibility AXPress action"
            }
        
        # Try AXClick action
        if self._click_accessibility_click():
            return {
                "method": "AXClick",
                "coordinates": None,
                "details": "Used accessibility AXClick action"
            }
        
        # Try mouse simulation as last resort
        return self._click_mouse_simulation()
    
    def _click_press(self):
        """Click using AXPress action."""
        try:
            if self.element.perform_action("AXPress"):
                logger.debug("Successfully clicked element with AXPress")
                return True
            return False
        except Exception as e:
            logger.error(f"AXPress click failed: {e}")
            return False
    
    def _click_accessibility_click(self):
        """Click using AXClick action."""
        try:
            if self.element.perform_action("AXClick"):
                logger.debug("Successfully clicked element with AXClick")
                return True
            return False
        except Exception as e:
            logger.error(f"AXClick click failed: {e}")
            return False
    
    def _click_mouse_simulation(self):
        """Click using mouse simulation."""
        try:
            x, y, width, height = self.bounds()
            
            # Calculate center point
            center_x = x + width / 2.0
            center_y = y + height / 2.0
            
            # Create events using Quartz
            event_source = CGEventSourceCreate(kCGEventSourceStateHIDSystemState)
            
            # Move mouse to position
            mouse_move = CGEventCreateMouseEvent(
                event_source, 
                kCGEventMouseMoved, 
                CGPointMake(center_x, center_y), 
                kCGMouseButtonLeft
            )
            CGEventPost(kCGHIDEventTap, mouse_move)
            
            # Brief pause
            time.sleep(0.05)
            
            # Mouse down
            mouse_down = CGEventCreateMouseEvent(
                event_source, 
                kCGEventLeftMouseDown, 
                CGPointMake(center_x, center_y), 
                kCGMouseButtonLeft
            )
            CGEventPost(kCGHIDEventTap, mouse_down)
            
            # Brief pause
            time.sleep(0.05)
            
            # Mouse up
            mouse_up = CGEventCreateMouseEvent(
                event_source, 
                kCGEventLeftMouseUp, 
                CGPointMake(center_x, center_y), 
                kCGMouseButtonLeft
            )
            CGEventPost(kCGHIDEventTap, mouse_up)
            
            logger.debug(f"Performed simulated mouse click at ({center_x}, {center_y})")
            
            return {
                "method": "MouseSimulation",
                "coordinates": (center_x, center_y),
                "details": f"Used mouse simulation at coordinates ({center_x:.1f}, {center_y:.1f})"
            }
        except Exception as e:
            logger.error(f"Mouse simulation failed: {e}")
            raise RuntimeError(f"Failed to perform mouse simulation: {e}")
    
    def type_text(self, text):
        """Type text into the element."""
        # First try to focus the element
        try:
            self.focus()
        except Exception:
            # If focus fails, try clicking
            try:
                self.click()
            except Exception as e:
                logger.warning(f"Both focus and click failed: {e}")
        
        # Try to set the AXValue attribute
        try:
            if self.element.set_attribute("AXValue", text):
                return True
        except Exception as e:
            logger.error(f"Could not set AXValue: {e}")
        
        # If direct setting fails, try keyboard simulation (not implemented here)
        logger.error("Failed to type text")
        return False
    
    def press_key(self, key_combo):
        """Press a key combination."""
        # Parse the key combo (e.g., "cmd+c")
        key_code, modifiers = self._parse_key_combination(key_combo)
        
        # Try to focus first
        try:
            self.focus()
        except Exception as e:
            logger.warning(f"Focus failed before key press: {e}")
            return False
        
        try:
            # Create event source
            event_source = CGEventSourceCreate(kCGEventSourceStateHIDSystemState)
            
            # Key down event with modifiers
            key_down = CGEventCreateKeyboardEvent(event_source, key_code, True)
            if modifiers:
                CGEventSetFlags(key_down, modifiers)
            CGEventPost(kCGHIDEventTap, key_down)
            
            # Brief pause
            time.sleep(0.05)
            
            # Key up event
            key_up = CGEventCreateKeyboardEvent(event_source, key_code, False)
            if modifiers:
                CGEventSetFlags(key_up, modifiers)
            CGEventPost(kCGHIDEventTap, key_up)
            
            logger.debug(f"Successfully pressed key combination: {key_combo}")
            return True
        except Exception as e:
            logger.error(f"Key press failed: {e}")
            return False
    
    def _parse_key_combination(self, key_combo):
        """Parse a key combination string like 'cmd+c'."""
        parts = [p.strip().lower() for p in key_combo.split('+')]
        
        if not parts:
            raise ValueError("Empty key combination")
        
        # The last part is the actual key
        key = parts[-1]
        key_code = self._get_key_code(key)
        
        # All previous parts are modifiers
        modifiers = 0
        for modifier in parts[:-1]:
            if modifier in ('cmd', 'command'):
                modifiers |= MODIFIER_COMMAND
            elif modifier == 'shift':
                modifiers |= MODIFIER_SHIFT
            elif modifier in ('alt', 'option'):
                modifiers |= MODIFIER_OPTION
            elif modifier in ('ctrl', 'control'):
                modifiers |= MODIFIER_CONTROL
            elif modifier == 'fn':
                modifiers |= MODIFIER_FN
            else:
                raise ValueError(f"Unknown modifier: {modifier}")
        
        return key_code, modifiers
    
    def _get_key_code(self, key):
        """Get key code for a key name."""
        key_map = {
            "return": KEY_RETURN,
            "enter": KEY_RETURN,
            "tab": KEY_TAB,
            "space": KEY_SPACE,
            "delete": KEY_DELETE,
            "backspace": KEY_DELETE,
            "esc": KEY_ESCAPE,
            "escape": KEY_ESCAPE,
            "left": KEY_ARROW_LEFT,
            "right": KEY_ARROW_RIGHT,
            "down": KEY_ARROW_DOWN,
            "up": KEY_ARROW_UP,
        }
        
        if key.lower() in key_map:
            return key_map[key.lower()]
        
        # For single character keys
        if len(key) == 1:
            # This is a simplification; proper implementation would map to macOS key codes
            return ord(key.lower())
        
        raise ValueError(f"Unknown key: {key}")
    
    def focus(self):
        """Set focus to the element."""
        # Try raising the element
        if self.element.perform_action("AXRaise"):
            logger.debug("Successfully raised element")
        
        # Try to directly set focus
        app_element = self._get_application()
        if app_element:
            if app_element.element.set_attribute("AXFocusedUIElement", self.element.element):
                logger.debug("Successfully set focus to element")
                return True
        
        # If direct focus fails, try clicking
        try:
            self.click()
            return True
        except Exception as e:
            logger.error(f"Focus failed: {e}")
            return False
    
    def _get_application(self):
        """Get the containing application element."""
        app_element = self.element.get_attribute("AXTopLevelUIElement")
        if app_element:
            return MacOSUIElement(ThreadSafeAXUIElement(app_element), 
                                 self.use_background_apps, 
                                 self.activate_app)
        return None
    
    def _macos_role_to_generic_role(self, role):
        """Map macOS-specific roles to generic roles."""
        role_map = {
            "AXWindow": "window",
            "AXButton": "button",
            "AXMenuItem": "button",
            "AXMenuBarItem": "button",
            "AXTextField": "textfield",
            "AXTextArea": "textfield",
            "AXTextEdit": "textfield",
            "AXSearchField": "textfield",
            "AXURIField": "urlfield",
            "AXAddressField": "urlfield",
            "AXList": "list",
            "AXCell": "listitem",
            "AXSheet": "dialog",
            "AXDialog": "dialog",
            "AXGroup": "group",
            "AXGenericElement": "genericElement",
            "AXWebArea": "webarea",
        }
        
        return role_map.get(role, role)


class MacOSEngine:
    """macOS Accessibility Engine implementation."""
    
    def __init__(self, use_background_apps=False, activate_app=True):
        """Initialize the engine."""
        self.use_background_apps = use_background_apps
        self.activate_app = activate_app
        self.system_wide = ThreadSafeAXUIElement.system_wide()
        
        # Check accessibility permissions
        if not self._check_accessibility_permissions():
            raise RuntimeError("Accessibility permissions not granted")
    
    def _check_accessibility_permissions(self, show_prompt=False):
        """Check if accessibility permissions are granted."""
        from HIServices import AXIsProcessTrustedWithOptions
        from CoreFoundation import CFDictionaryCreate, kCFTypeDictionaryKeyCallBacks, kCFTypeDictionaryValueCallBacks
        
        # Create the options dictionary
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
        
        # Call AXIsProcessTrustedWithOptions
        is_trusted = AXIsProcessTrustedWithOptions(options)
        
        if is_trusted:
            logger.info("Accessibility permissions are granted")
            return True
        else:
            if show_prompt:
                logger.info("Accessibility permissions prompt displayed")
                return False
            else:
                logger.warning("Accessibility permissions not granted")
                logger.info("**************************************************************")
                logger.info("* ACCESSIBILITY PERMISSIONS REQUIRED                          *")
                logger.info("* Go to System Preferences > Security & Privacy > Privacy >   *")
                logger.info("* Accessibility and add this application.                     *")
                logger.info("* Without this permission, UI automation will not function.   *")
                logger.info("**************************************************************")
                return False
    
    def get_applications(self):
        """Get all running applications."""
        app_elements = []
        
        # Get running application PIDs using NSWorkspace
        workspace = AppKit.NSWorkspace.sharedWorkspace()
        running_apps = workspace.runningApplications()
        
        for app in running_apps:
            # Filter based on activation policy
            if not self.use_background_apps:
                # NSApplicationActivationPolicyRegular = 0
                # NSApplicationActivationPolicyAccessory = 1
                # NSApplicationActivationPolicyProhibited = 2 (background only)
                if app.activationPolicy() in [1, 2]:
                    continue
            
            # Filter out common background workers
            bundle_id = app.bundleIdentifier()
            if bundle_id:
                if any(substr in bundle_id for substr in [
                    ".worker", "com.apple.WebKit", "com.apple.CoreServices",
                    ".helper", ".agent"
                ]):
                    continue
            
            # Create accessibility element for the app
            pid = app.processIdentifier()
            app_element = ThreadSafeAXUIElement.application(pid)
            app_elements.append(MacOSUIElement(app_element, 
                                             self.use_background_apps, 
                                             self.activate_app))
        
        return app_elements
    
    def get_application_by_name(self, name):
        """Find an application by its name."""
        # Refresh accessibility tree
        self._refresh_accessibility_tree(name)
        
        # Get all applications and filter by name
        apps = self.get_applications()
        name_lower = name.lower()
        
        for app in apps:
            app_attrs = app.attributes()
            app_name = app_attrs.get("label", "")
            
            if app_name.lower() == name_lower:
                logger.debug(f"Found matching application: '{app_name}'")
                return app
        
        raise ValueError(f"Application '{name}' not found")
    
    def _refresh_accessibility_tree(self, app_name=None):
        """Refresh the accessibility tree."""
        if not self.activate_app:
            return
        
        logger.debug("Refreshing accessibility tree")
        
        if app_name:
            # Try to activate the app first
            workspace = AppKit.NSWorkspace.sharedWorkspace()
            running_apps = workspace.runningApplications()
            
            for app in running_apps:
                curr_app_name = app.localizedName()
                if curr_app_name and curr_app_name.lower() == app_name.lower():
                    app.activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps)
                    logger.debug(f"Activated application: {app_name}")
                    time.sleep(0.1)  # Give system time to update
                    break
        
        # Force a refresh by querying the system-wide element
        self.system_wide.get_attribute_names()
    
    def open_application(self, app_name):
        """Open an application by name."""
        logger.info(f"Opening application: {app_name}")
        
        # Use the 'open' command to launch the application
        import subprocess
        result = subprocess.run(['open', '-a', app_name], capture_output=True)
        
        if result.returncode != 0:
            error_msg = result.stderr.decode('utf-8')
            logger.error(f"Failed to open application '{app_name}': {error_msg}")
            raise RuntimeError(f"Failed to open application '{app_name}': {error_msg}")
        
        logger.info(f"Open command executed successfully for {app_name}")
        
        # For Firefox specifically, try an alternative approach first
        if app_name.lower() == "firefox":
            logger.info("Using specialized Firefox detection logic")
            try:
                # Get all running processes using ps command
                ps_result = subprocess.run(['ps', 'aux'], capture_output=True, text=True)
                if ps_result.returncode == 0:
                    for line in ps_result.stdout.splitlines():
                        if 'firefox' in line.lower():
                            logger.info(f"Found Firefox process: {line}")
                            
                # Use AppleScript to check if Firefox is running and get its PID
                script = """tell application "System Events"
                set firefoxProcesses to a reference to (processes where name contains "Firefox")
                if length of firefoxProcesses is greater than 0 then
                    set firefoxProcess to first item of firefoxProcesses
                    return {true, name of firefoxProcess, unix id of firefoxProcess}
                else
                    return {false, "", 0}
                end if
                end tell"""
                
                ascript_result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
                logger.info(f"AppleScript result: {ascript_result.stdout.strip()}")
                
                # Parse the AppleScript result which returns {true/false, name, pid}
                if "true" in ascript_result.stdout and "," in ascript_result.stdout:
                    parts = ascript_result.stdout.strip().strip("{}").split(",")
                    if len(parts) >= 3:
                        firefox_pid = int(parts[2].strip())
                        firefox_name = parts[1].strip()
                        logger.info(f"Found Firefox via AppleScript: name={firefox_name}, pid={firefox_pid}")
                        
                        if firefox_pid > 0:
                            # Create an accessibility element from the PID
                            app_element = ThreadSafeAXUIElement.application(firefox_pid)
                            logger.info("Created AXUIElement for Firefox")
                            
                            # Wait a moment to ensure Firefox is ready
                            time.sleep(1.5)
                            
                            return MacOSUIElement(app_element, self.use_background_apps, self.activate_app)
            except Exception as e:
                logger.warning(f"Firefox-specific detection failed: {e}")
        
        # Wait for app to launch - increase timeout and delay for slow apps
        max_retries = 30  # Increased from 20
        retry_delay = 1.0  # Increased from 0.5
        
        # First wait to make sure the app shows up in NSWorkspace
        logger.info(f"Waiting for {app_name} to appear in NSWorkspace")
        for attempt in range(max_retries):
            try:
                workspace = AppKit.NSWorkspace.sharedWorkspace()
                running_apps = workspace.runningApplications()
                
                logger.info(f"Found {len(running_apps)} running applications")
                
                # Log all running applications to help with debugging
                if attempt % 5 == 0:  # Only log every 5 attempts to avoid too much output
                    for i, app in enumerate(running_apps):
                        found_name = app.localizedName() or "Unknown"
                        bundle_id = app.bundleIdentifier() or "Unknown"
                        pid = app.processIdentifier()
                        logger.info(f"Running app #{i}: '{found_name}' (Bundle: {bundle_id}, PID: {pid})")
                
                for app in running_apps:
                    found_name = app.localizedName() or ""
                    if found_name and app_name.lower() in found_name.lower():
                        # The app is in the workspace, give it more time to initialize
                        logger.info(f"Found {app_name} in workspace, Name: {found_name}, PID: {app.processIdentifier()}")
                        # Give the app more time to initialize its accessibility elements
                        time.sleep(2.0)
                        
                        # Try to get its accessibility element
                        pid = app.processIdentifier()
                        app_element = ThreadSafeAXUIElement.application(pid)
                        element = MacOSUIElement(app_element, self.use_background_apps, self.activate_app)
                        
                        try:
                            # Double check by getting some attribute to ensure it's valid
                            # This will force the accessibility API to initialize
                            attrs = element.attributes()
                            logger.info(f"Successfully opened and accessed {app_name} with attributes: {attrs}")
                            return element
                        except Exception as attr_err:
                            logger.warning(f"Could get element but failed to get attributes: {attr_err}")
                            # Still return the element even if attributes fail
                            # Sometimes this can succeed later even if it fails initially
                            logger.info(f"Returning element anyway for {app_name}")
                            return element
                    
                    # Check bundle identifier for common apps
                    bundle_id = app.bundleIdentifier() or ""
                    # Firefox has bundle ID org.mozilla.firefox
                    if app_name.lower() == "firefox" and bundle_id and "firefox" in bundle_id.lower():
                        pid = app.processIdentifier()
                        logger.info(f"Found Firefox via bundle ID: {bundle_id} with PID {pid}")
                        app_element = ThreadSafeAXUIElement.application(pid)
                        element = MacOSUIElement(app_element, self.use_background_apps, self.activate_app)
                        return element
                    # Chrome has bundle ID com.google.Chrome
                    elif app_name.lower() == "chrome" and bundle_id and "chrome" in bundle_id.lower():
                        pid = app.processIdentifier()
                        logger.info(f"Found Chrome via bundle ID: {bundle_id} with PID {pid}")
                        app_element = ThreadSafeAXUIElement.application(pid)
                        element = MacOSUIElement(app_element, self.use_background_apps, self.activate_app)
                        return element
            except Exception as e:
                logger.warning(f"Error during app lookup (attempt {attempt+1}): {e}")
                
            logger.info(f"App not fully initialized yet, waiting... (attempt {attempt+1}/{max_retries})")
            time.sleep(retry_delay)
        
        # If we reach here, we've exhausted retries, try a more brute-force approach
        logger.info("Trying ps command to find application process")
        try:
            # Use 'ps' command to find the process
            process = subprocess.run(['ps', 'aux'], capture_output=True, text=True)
            if process.returncode == 0:
                for line in process.stdout.splitlines():
                    line_lower = line.lower()
                    app_lower = app_name.lower()
                    if app_lower in line_lower:
                        logger.info(f"Found potential {app_name} process: {line}")
                        # Try to extract PID (second column in ps output)
                        parts = line.split()
                        if len(parts) > 1:
                            try:
                                pid = int(parts[1])
                                logger.info(f"Extracted PID {pid} for {app_name}")
                                app_element = ThreadSafeAXUIElement.application(pid)
                                return MacOSUIElement(app_element, self.use_background_apps, self.activate_app)
                            except (ValueError, IndexError):
                                logger.warning("Failed to extract PID from ps output")
        except Exception as e:
            logger.warning(f"Error using ps to find process: {e}")
        
        # Last resort - try the standard method
        logger.info("All automatic detection methods failed, trying standard method")
        try:
            self._refresh_accessibility_tree(app_name)
            return self.get_application_by_name(app_name)
        except Exception as e:
            logger.error(f"Final attempt to find app failed: {e}")
            
            # One final hail mary attempt for Firefox specifically
            if app_name.lower() == "firefox":
                logger.info("Making one last attempt for Firefox using a browser search")
                try:
                    # Look for any app with 'browser' in the name or bundle ID
                    workspace = AppKit.NSWorkspace.sharedWorkspace()
                    running_apps = workspace.runningApplications()
                    
                    for app in running_apps:
                        found_name = app.localizedName() or ""
                        bundle_id = app.bundleIdentifier() or ""
                        
                        browser_keywords = ["firefox", "browser", "web", "mozilla"]
                        name_match = any(keyword in found_name.lower() for keyword in browser_keywords)
                        bundle_match = any(keyword in bundle_id.lower() for keyword in browser_keywords)
                        
                        if name_match or bundle_match:
                            pid = app.processIdentifier()
                            logger.info(f"Found browser-like app: {found_name} ({bundle_id}) with PID {pid}")
                            app_element = ThreadSafeAXUIElement.application(pid)
                            return MacOSUIElement(app_element, self.use_background_apps, self.activate_app)
                except Exception as final_e:
                    logger.error(f"Final browser search attempt failed: {final_e}")
                    
            # If we got here, we've exhausted all options
            raise RuntimeError(f"Application '{app_name}' not found after multiple attempts (including special handling)")
    
    def open_url(self, url, browser=None):
        """Open a URL in a browser."""
        logger.debug(f"Opening URL: {url} in browser: {browser}")
        
        import subprocess
        if browser:
            # Open URL in specific browser
            result = subprocess.run(['open', '-a', browser, url], capture_output=True)
        else:
            # Open URL in default browser
            result = subprocess.run(['open', url], capture_output=True)
        
        if result.returncode != 0:
            error_msg = result.stderr.decode('utf-8')
            raise RuntimeError(f"Failed to open URL '{url}': {error_msg}")
        
        # Give the browser a moment to launch
        time.sleep(1.0)
        
        # If a specific browser was requested, try to return its UI element
        if browser:
            try:
                self._refresh_accessibility_tree(browser)
                return self.get_application_by_name(browser)
            except Exception as e:
                logger.warning(f"Could not get browser element: {e}")
                return None
        else:
            # Can't reliably determine which browser was used
            return None
    
    def find_element(self, selector, root_element=None):
        """Find an element matching the selector."""
        start_element = root_element.element if root_element else self.system_wide
        
        # Implement basic element finding - this is simplified
        if selector.get("role"):
            # Convert generic role to macOS roles
            macos_roles = self._map_generic_role_to_macos_roles(selector["role"])
            
            # Find elements with matching role
            def matcher(element):
                element_role = element.get_role()
                return element_role and element_role in macos_roles
            
            return self._find_element_recursive(start_element, matcher)
        
        elif selector.get("id"):
            # Find element with matching ID
            target_id = selector["id"]
            
            def matcher(element):
                # Using simplified ID matching
                el_id = MacOSUIElement(element).id()
                return el_id == target_id
            
            return self._find_element_recursive(start_element, matcher)
        
        elif selector.get("name"):
            # Find element with matching name/title
            target_name = selector["name"]
            
            def matcher(element):
                title = element.get_title()
                return title and title == target_name
            
            return self._find_element_recursive(start_element, matcher)
        
        elif selector.get("text"):
            target_text = selector["text"]
            
            def matcher(element):
                # Check title
                title = element.get_title()
                if title and target_text in title:
                    return True
                
                # Check value
                value = element.get_attribute("AXValue")
                if value and target_text in CFCopyDescription(value):
                    return True
                
                # Check description
                desc = element.get_attribute("AXDescription")
                if desc and target_text in CFCopyDescription(desc):
                    return True
                
                return False
            
            return self._find_element_recursive(start_element, matcher)
        
        raise ValueError("Unsupported selector type")
    
    def _find_element_recursive(self, element, matcher_fn):
        """Recursively search for an element matching the criteria."""
        # Check if the current element matches
        if matcher_fn(element):
            return MacOSUIElement(element, self.use_background_apps, self.activate_app)
        
        # Check all children
        children = element.get_children()
        for child in children:
            result = self._find_element_recursive(child, matcher_fn)
            if result:
                return result
        
        # Check all windows
        windows = element.get_windows()
        for window in windows:
            result = self._find_element_recursive(window, matcher_fn)
            if result:
                return result
        
        # No match found
        return None
    
    def _map_generic_role_to_macos_roles(self, role):
        """Map generic role to macOS-specific roles."""
        role_map = {
            "window": ["AXWindow"],
            "button": ["AXButton", "AXMenuItem", "AXMenuBarItem", "AXStaticText", "AXImage"],
            "checkbox": ["AXCheckBox"],
            "menu": ["AXMenu"],
            "menuitem": ["AXMenuItem", "AXMenuBarItem"],
            "dialog": ["AXSheet", "AXDialog"],
            "text": ["AXTextField", "AXTextArea", "AXText", "AXComboBox", "AXTextEdit", 
                     "AXSearchField", "AXWebArea", "AXGroup", "AXGenericElement", 
                     "AXURIField", "AXAddressField", "AXStaticText"],
            "textfield": ["AXTextField", "AXTextArea", "AXText", "AXComboBox", "AXTextEdit", 
                          "AXSearchField", "AXWebArea", "AXGroup", "AXGenericElement", 
                          "AXURIField", "AXAddressField", "AXStaticText"],
            "input": ["AXTextField", "AXTextArea", "AXText", "AXComboBox", "AXTextEdit", 
                      "AXSearchField", "AXWebArea", "AXGroup", "AXGenericElement", 
                      "AXURIField", "AXAddressField", "AXStaticText"],
            "textbox": ["AXTextField", "AXTextArea", "AXText", "AXComboBox", "AXTextEdit", 
                        "AXSearchField", "AXWebArea", "AXGroup", "AXGenericElement", 
                        "AXURIField", "AXAddressField", "AXStaticText"],
            "url": ["AXTextField", "AXURIField", "AXAddressField"],
            "urlfield": ["AXTextField", "AXURIField", "AXAddressField"],
            "list": ["AXList"],
            "listitem": ["AXCell"],
            "combobox": ["AXPopUpButton", "AXComboBox"],
            "tab": ["AXTabGroup"],
            "tabitem": ["AXRadioButton"],
            "toolbar": ["AXToolbar"],
        }
        
        return role_map.get(role.lower(), [role])
