"""
UI traversal logic for macOS UI Monitoring.
This module handles traversal of UI elements and extraction of data from applications.
"""

import time
import logging
import json
import subprocess
from datetime import datetime
from typing import Any, Dict, Optional

from macos_accessibility import ThreadSafeAXUIElement, MacOSUIElement

from osmonitor.core.elements import ElementAttributes, WindowState, WindowIdentifier, UIFrame

logger = logging.getLogger(__name__)

def traverse_ui_elements(self_obj, ax_app, app_name, window_name):
    """Traverse UI elements of the application to build element tree.
    
    Args:
        self_obj: The MacOSUIMonitor instance
        ax_app: The accessibility application element
        app_name: The name of the application
        window_name: The name of the window
    """
    self_obj.is_traversing = True
    self_obj.should_cancel_traversal = False
    
    try:
        # Initialize window state if needed
        with self_obj.lock:
            if app_name not in self_obj.global_element_values:
                self_obj.global_element_values[app_name] = {}
            if window_name not in self_obj.global_element_values[app_name]:
                self_obj.global_element_values[app_name][window_name] = WindowState()
            
            window_state = self_obj.global_element_values[app_name][window_name]
            window_state.elements.clear()  # Clear existing elements
            window_state.timestamp = datetime.now()
        
        # Function to recursively traverse elements
        def traverse(element, path="", depth=0):
            if self_obj.should_cancel_traversal:
                return None
            
            if element is None:
                return None
                
            try:
                # Get basic attributes
                element_role = element.get_role() or "unknown"
                element_title = element.get_title() or ""
                element_value = element.get_value()
                element_desc = element.get_description() or ""
                
                # Get position and size
                position = element.get_position()
                size = element.get_size()
                if position and size:
                    x, y = position
                    width, height = size
                else:
                    x = y = width = height = 0
                
                # Create element attributes object
                element_path = f"{path}/{element_role}[{element_title or element_desc}]"
                attributes = {
                    "Role": element_role,
                    "Title": element_title,
                    "Value": element_value,
                    "Description": element_desc
                }
                
                # Check for additional UI-specific attributes
                for attr_name in ["AXPlaceholderValue", "AXURL", "AXLabel"]:
                    try:
                        attr_val = element.get_attribute(attr_name)
                        if attr_val:
                            attributes[attr_name.replace("AX", "")] = attr_val
                    except:
                        pass
                
                # Create element object
                elem = ElementAttributes(
                    element_ref=None,  # We don't store references as they may become invalid
                    path=element_path,
                    attributes=attributes,
                    depth=depth,
                    x=x, y=y, width=width, height=height,
                    children=[]  # Children will be added later
                )
                
                # Store element in window state
                with self_obj.lock:
                    window_state = self_obj.global_element_values[app_name][window_name]
                    window_state.elements[elem.identifier] = elem
                
                # Get children and traverse them
                try:
                    children = element.get_children()
                    for child in children:
                        child_elem = traverse(child, element_path, depth + 1)
                        if child_elem:
                            elem.children.append(child_elem.identifier)
                except Exception as e:
                    logger.debug(f"Error getting children: {e}")
                
                return elem
                
            except Exception as e:
                logger.debug(f"Error traversing element: {e}")
                return None
        
        # Start traversal from the application element
        app_elem = traverse(ax_app, f"{app_name}", 0)
        
        # Update text output from collected elements
        all_text = []
        with self_obj.lock:
            window_state = self_obj.global_element_values[app_name][window_name]
            
            # Collect text from all elements
            for elem in window_state.elements.values():
                if "Value" in elem.attributes and elem.attributes["Value"]:
                    val = elem.attributes["Value"]
                    if isinstance(val, str) and val.strip():
                        all_text.append(val.strip())
            
            # Join all text and store it
            window_state.text_output = "\n".join(all_text)
            window_state.initial_traversal_at = datetime.now()
            
            # Mark window as changed
            self_obj.changed_windows.add(WindowIdentifier(app=app_name, window=window_name))
            
            # Send update via named pipe if configured
            if self_obj.named_pipe_handle is not None:
                ui_frame = UIFrame(
                    window=window_name,
                    app=app_name,
                    text_output=window_state.text_output,
                    initial_traversal_at=window_state.initial_traversal_at.isoformat()
                )
                write_to_pipe(self_obj, ui_frame)
        
        self_obj._log_ui_event("traversal_complete", {
            "app": app_name,
            "window": window_name,
            "element_count": len(window_state.elements)
        })
        
        logger.info(f"UI traversal complete for {app_name}, {window_name}: {len(window_state.elements)} elements")
        
    except Exception as e:
        logger.error(f"Error during UI traversal: {e}")
        
    finally:
        self_obj.is_traversing = False

def get_ui_data_via_applescript(self_obj, app_name, window_name):
    """Get UI data using AppleScript as a fallback.
    
    Args:
        self_obj: The MacOSUIMonitor instance
        app_name: The name of the application
        window_name: The name of the window
    """
    try:
        # Get text content from the current window using AppleScript
        script = f'''
        tell application "System Events"
            set frontApp to first process whose name is "{app_name}"
            set allTexts to {{}}
            tell frontApp
                set allWindows to every window
                repeat with aWindow in allWindows
                    set windowName to name of aWindow
                    if windowName contains "{window_name}" then
                        -- Get all UI elements text
                        set uiElements to every UI element of aWindow
                        repeat with elem in uiElements
                            try
                                set elemValue to value of elem
                                if elemValue is not missing value and elemValue is not "" then
                                    set end of allTexts to elemValue
                                end if
                            end try
                            
                            try
                                set elemDesc to description of elem
                                if elemDesc is not missing value and elemDesc is not "" then
                                    set end of allTexts to elemDesc
                                end if
                            end try
                        end repeat
                    end if
                end repeat
            end tell
            return allTexts
        end tell
        '''
        
        # Run the AppleScript
        result = subprocess.run(['osascript', '-e', script], 
                              capture_output=True, text=True)
        
        if result.returncode == 0 and result.stdout:
            # Process the returned text
            text_content = result.stdout.strip()
            
            # Update the window state
            with self_obj.lock:
                if app_name in self_obj.global_element_values and window_name in self_obj.global_element_values[app_name]:
                    window_state = self_obj.global_element_values[app_name][window_name]
                    
                    # Create a basic UI element representation
                    element = ElementAttributes(
                        element_ref=None,
                        path=f"{app_name} -> {window_name}",
                        attributes={"Value": text_content},
                        depth=0,
                        x=0, y=0, width=0, height=0,
                        children=[]
                    )
                    
                    # Add to window state
                    window_state.elements[element.identifier] = element
                    window_state.timestamp = datetime.now()
                    window_state.text_output = text_content
                    
                    # Mark as changed
                    self_obj.changed_windows.add(WindowIdentifier(app=app_name, window=window_name))
                    
                    # Send update via named pipe if configured
                    if self_obj.named_pipe_handle is not None:
                        ui_frame = UIFrame(
                            window=window_name,
                            app=app_name,
                            text_output=text_content,
                            initial_traversal_at=window_state.timestamp.isoformat()
                        )
                        write_to_pipe(self_obj, ui_frame)
    except Exception as e:
        logger.error(f"Failed to get UI data via AppleScript: {e}")

def write_to_pipe(self_obj, ui_frame):
    """Write UI frame data to the named pipe if configured.
    
    Args:
        self_obj: The MacOSUIMonitor instance
        ui_frame: The UIFrame object to write
    """
    if self_obj.named_pipe_handle is None:
        return
        
    try:
        data = json.dumps(ui_frame.__dict__)
        self_obj.named_pipe_handle.write(f"{data}\n".encode('utf-8'))
        self_obj.named_pipe_handle.flush()
    except Exception as e:
        logger.error(f"Error writing to named pipe: {e}")

def setup_accessibility_notifications(self_obj, pid, ax_app, app_name, window_name):
    """Set up accessibility notifications for the application.
    
    Args:
        self_obj: The MacOSUIMonitor instance
        pid: The process ID of the application
        ax_app: The accessibility application element
        app_name: The name of the application
        window_name: The name of the window
    """
    # This would normally set up event observers for accessibility events
    # Implementation depends on the specific accessibility API being used
    pass

def stop_observer(self_obj):
    """Stop any running accessibility observers.
    
    Args:
        self_obj: The MacOSUIMonitor instance
    """
    # Implementation would depend on the specific accessibility API
    pass