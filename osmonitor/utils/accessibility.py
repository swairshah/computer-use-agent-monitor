"""
Accessibility utilities for macOS UI Monitoring.
This module provides utility functions for dealing with the macOS Accessibility API.
"""

import logging

# PyObjC imports for accessibility permissions
from HIServices import AXIsProcessTrustedWithOptions
from CoreFoundation import CFDictionaryCreate, kCFTypeDictionaryKeyCallBacks, kCFTypeDictionaryValueCallBacks

logger = logging.getLogger(__name__)

def check_accessibility_permissions(show_prompt=True):
    """Check if accessibility permissions are granted.
    
    Args:
        show_prompt: Whether to display the permissions prompt if not granted
        
    Returns:
        bool: True if permissions are granted, False otherwise
    """
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

def clean_accessibility_value(value):
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