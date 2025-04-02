"""
Text selection monitoring functionality for macOS UI Monitoring.
This module provides classes and functions for monitoring text selections.
"""

import time
import logging
import threading
import subprocess

from osmonitor.core.events import UIEvent

logger = logging.getLogger(__name__)

class TextSelectionMonitor:
    """Class for handling text selection monitoring."""
    
    def __init__(self, on_event_callback, current_app_getter, current_element_getter,
                 interval=1.0, change_threshold=3.0):
        """Initialize the text selection monitor.
        
        Args:
            on_event_callback: Callback function that takes a UIEvent
            current_app_getter: Function that returns the current application
            current_element_getter: Function that returns the current element
            interval: Polling interval in seconds
            change_threshold: Minimum time between selection events
        """
        self.on_event_callback = on_event_callback
        self.get_current_app = current_app_getter
        self.get_current_element = current_element_getter
        self.interval = interval
        self.change_threshold = change_threshold
        self.last_selection = None
        self.running = False
        self.thread = None
    
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
            current_element = self.get_current_element()
            if current_element:
                # Try to get selected text directly
                selected_text = current_element.element.get_attribute("AXSelectedText")
                if selected_text:
                    return selected_text
                
                # If no selected text but value exists, try to determine selection from value
                value = current_element.element.get_attribute("AXValue")
                selected_range = current_element.element.get_attribute("AXSelectedTextRange")
                
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
    
    def _monitor_selection(self):
        """Background thread that monitors text selections."""
        logger.info("Text selection monitoring thread started")
        last_selection_time = 0
        
        while self.running:
            try:
                # Don't check too frequently
                time.sleep(self.interval)
                
                # Check if enough time has passed since the last selection event
                now = time.time()
                if now - last_selection_time < self.change_threshold:
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
                
                # Get app name
                app_name = "Unknown"
                current_app = self.get_current_app()
                if current_app:
                    try:
                        app_name = current_app.element.get_title() or "Unknown"
                    except:
                        pass
                
                # Create a selection event
                event = UIEvent(
                    "text_selection",
                    now,
                    text=selection,
                    source=source,
                    app_name=app_name
                )
                
                # Call the callback
                self.on_event_callback(event)
                
                # Update tracking variables
                self.last_selection = selection
                last_selection_time = now
                
                # Log the selection
                logger.info(f"Text selection: {display_selection} [from {source}]")
                
            except Exception as e:
                logger.debug(f"Error checking selection: {e}")
    
    def start(self):
        """Start text selection monitoring."""
        if self.running:
            logger.warning("Text selection monitoring is already running")
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._monitor_selection)
        self.thread.daemon = True
        self.thread.start()
        logger.info(f"Text selection monitoring started (polling every {self.interval:.1f}s)")
    
    def stop(self):
        """Stop text selection monitoring."""
        if not self.running:
            return
        
        self.running = False
        # The thread will terminate on its own since it checks self.running