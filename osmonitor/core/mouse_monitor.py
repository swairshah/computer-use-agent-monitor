"""
Mouse monitoring functionality for macOS UI Monitoring.
This module provides classes and functions for monitoring mouse events.
"""

import time
import logging
import threading
import AppKit

from osmonitor.core.events import UIEvent
from osmonitor.core.elements import ElementInfo
from macos_accessibility import ThreadSafeAXUIElement, MacOSUIElement

logger = logging.getLogger(__name__)

class MouseMonitor:
    """Class for handling mouse event monitoring."""
    
    def __init__(self, system_wide, on_event_callback):
        """Initialize the mouse monitor.
        
        Args:
            system_wide: System-wide accessibility element
            on_event_callback: Callback function that takes a UIEvent
        """
        self.system_wide = system_wide
        self.on_event_callback = on_event_callback
        self.mouse_position = (0, 0)
        self.last_click_position = None
        self.last_click_element = None
        self.running = False
        self.thread = None
        
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
    
    def _track_mouse(self):
        """Track mouse movements and clicks."""
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
                    # mouse_event = UIEvent("mouse_move", time.time(), 
                    #                     position={"x": pos[0], "y": pos[1]})
                    # self.on_event_callback(mouse_event)
                
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
                    
                    click_event = None
                    if element_at_position:
                        self.last_click_element = element_at_position
                        element_info = ElementInfo(element_at_position)
                        
                        # Create click event with element info
                        click_event = UIEvent(
                            "click",
                            current_time,
                            button=button,
                            position={"x": self.mouse_position[0], "y": self.mouse_position[1]},
                            element=element_info.to_dict()
                        )
                        
                        # Log with more compact representation
                        title_str = f'"{element_info.title}"' if element_info.title else "No title"
                        logger.info(f"{button.title()} click at {self.mouse_position} on {title_str} ({element_info.role})")
                    else:
                        # Create click event without element info
                        click_event = UIEvent(
                            "click",
                            current_time,
                            button=button,
                            position={"x": self.mouse_position[0], "y": self.mouse_position[1]},
                            element=None
                        )
                        
                        logger.info(f"{button.title()} click at {self.mouse_position}")
                    
                    # Notify about the click
                    if click_event:
                        self.on_event_callback(click_event)
                    
                    prev_click_time = current_time
                
            except Exception as e:
                logger.error(f"Error tracking mouse: {e}")
            
            # Polling interval for mouse
            time.sleep(0.05)
    
    def start(self):
        """Start mouse monitoring."""
        if self.running:
            logger.warning("Mouse monitoring is already running")
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._track_mouse)
        self.thread.daemon = True
        self.thread.start()
        logger.info("Mouse monitoring started")
    
    def stop(self):
        """Stop mouse monitoring."""
        if not self.running:
            return
        
        self.running = False
        
        # The thread will terminate on its own since it checks self.running