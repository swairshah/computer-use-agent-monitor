"""
Screenshot functionality for macOS UI Monitoring.
This module provides functions for capturing screenshots.
"""

import os
import re
import logging
from datetime import datetime

import AppKit
from Quartz import CGDisplayCreateImage, CGMainDisplayID, CGImageGetWidth, CGImageGetHeight

logger = logging.getLogger(__name__)

def capture_screenshot(screenshot_dir, mouse_position, current_element=None, counter=None):
    """Capture a screenshot of the main display with mouse coordinates.
    
    Args:
        screenshot_dir: Directory to save the screenshot in
        mouse_position: Tuple of (x, y) coordinates of the mouse
        current_element: Current UI element (optional)
        counter: Screenshot counter (optional)
        
    Returns:
        Path to the screenshot if successful, None otherwise
    """
    if not screenshot_dir:
        logger.warning("Screenshot directory not set, not capturing screenshot")
        return None
        
    try:
        # Ensure screenshot directory exists
        os.makedirs(screenshot_dir, exist_ok=True)
        
        # Get main display ID
        display_id = CGMainDisplayID()
        
        # Create screenshot image
        screenshot = CGDisplayCreateImage(display_id)
        if screenshot is None:
            logger.error("Failed to create screenshot image")
            return None
        
        # Get width and height
        width = CGImageGetWidth(screenshot)
        height = CGImageGetHeight(screenshot)
        
        # Get the timestamp for the filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Use counter or default to 1
        screenshot_counter = counter or 1
        
        # Extract mouse coordinates
        mouse_x, mouse_y = mouse_position
        
        # Create filename with mouse coordinates and counter
        filename = f"screenshot_{screenshot_counter:06d}_mouse_{int(mouse_x)}_{int(mouse_y)}_{timestamp}.png"
        
        # If we have element info, add a sanitized version of the title
        if current_element:
            try:
                if hasattr(current_element, 'title') and current_element.title:
                    # Sanitize title for filename - keep only alphanumeric chars
                    safe_title = re.sub(r'[^\w]', '_', current_element.title)[:30]
                    filename = f"screenshot_{screenshot_counter:06d}_{safe_title}_mouse_{int(mouse_x)}_{int(mouse_y)}_{timestamp}.png"
            except Exception:
                pass  # If we can't get element info, just use the default filename
                
        filepath = os.path.join(screenshot_dir, filename)
        
        # Convert to NSImage and save
        ns_image = AppKit.NSImage.alloc().initWithCGImage_size_(
            screenshot, 
            AppKit.NSMakeSize(width, height)
        )
        
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