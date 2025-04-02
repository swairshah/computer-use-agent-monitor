"""
Keyboard monitoring functionality for macOS UI Monitoring.
This module provides classes and functions for monitoring keyboard events.
"""

import time
import logging
import threading
import os

# Import keyboard-related modules
import AppKit
from Quartz import (
    CGEventGetLocation,
    CGEventGetIntegerValueField,
    CGEventGetFlags,
    kCGKeyboardEventKeycode,
    kCGEventKeyDown,
    kCGEventKeyUp,
    kCGEventFlagsChanged,
    CGEventTapCreate,
    CGEventMaskBit,
    kCGEventTapOptionDefault,
    kCGHeadInsertEventTap,
    kCGSessionEventTap,
    CGEventTapEnable
)

from CoreFoundation import (
    CFRunLoopGetCurrent,
    CFRunLoopAddSource,
    kCFRunLoopCommonModes,
    CFMachPortCreateRunLoopSource
)

# Import from our own modules
from osmonitor.utils.key_mapping import KEY_CODE_MAP, parse_modifier_flags
from osmonitor.core.events import UIEvent
from osmonitor.utils.accessibility import check_accessibility_permissions

logger = logging.getLogger(__name__)

class KeyboardMonitor:
    """Class for handling keyboard event monitoring."""
    
    def __init__(self, on_event_callback, key_log_file=None):
        """Initialize the keyboard monitor.
        
        Args:
            on_event_callback: Callback function that takes a UIEvent
            key_log_file: Optional file to log keyboard events to
        """
        self.on_event_callback = on_event_callback
        self.key_log_file = key_log_file
        self.running = False
        self.keyboard_listener = None
        self.modifier_state = {
            "shift": False,
            "control": False,
            "option": False,
            "command": False,
            "fn": False,
            "capslock": False
        }
    
    def setup_event_tap(self):
        """Set up an event tap to monitor keyboard events."""
        try:
            # Log that we're setting up event tap
            logger.error("Setting up keyboard event tap")
            
            # First check if we have accessibility permissions
            if not check_accessibility_permissions(False):
                logger.error("ERROR: No accessibility permissions. Keyboard events will not be detected.")
                return False
            
            # Create mask for keyboard events
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
                    # Process based on event type
                    if event_type == kCGEventKeyDown:
                        # Get key code and character
                        keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
                        
                        # Log for debugging
                        direct_log_key(f"KeyDown event: keycode={keycode}")
                        
                        # Try to convert keycode to character
                        char = ""
                        try:
                            # Create an NSEvent from the CGEvent to get the characters
                            ns_event = AppKit.NSEvent.eventWithCGEvent_(event)
                            if ns_event:
                                char = ns_event.characters() or ""
                        except Exception as e:
                            direct_log_key(f"Error getting characters: {e}")
                                
                        # Get current modifier keys state
                        flags = CGEventGetFlags(event)
                        modifiers = parse_modifier_flags(flags)
                        
                        # Add key name if available
                        key_name = KEY_CODE_MAP.get(keycode, "")
                        
                        # Create the UI event
                        key_event = UIEvent(
                            "key_press",
                            time.time(),
                            keycode=keycode,
                            character=char,
                            key_name=key_name,
                            modifiers=modifiers
                        )
                        
                        # Call the callback
                        self.on_event_callback(key_event)
                        
                        # Format for logging
                        key_display = char or key_name or f"keycode {keycode}"
                        mod_str = ""
                        active_mods = [name for name, active in modifiers.items() if active]
                        if active_mods:
                            mod_str = f" with modifiers: {'+'.join(active_mods)}"
                        
                        # Log the event
                        logger.error(f"KEY PRESS: {key_display}{mod_str}")
                        
                        # Write to key log file
                        if self.key_log_file:
                            try:
                                timestamp = time.time()
                                mod_list = '+'.join(active_mods) if active_mods else ""
                                
                                # Ensure directory exists
                                log_dir = os.path.dirname(os.path.abspath(self.key_log_file))
                                os.makedirs(log_dir, exist_ok=True)
                                
                                # Use low-level file operations
                                log_fd = os.open(self.key_log_file, 
                                               os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
                                os.write(log_fd, f"{timestamp},key_press,{key_display},{mod_list}\n".encode('utf-8'))
                                os.close(log_fd)
                            except Exception as e:
                                logger.error(f"Failed to write to key log file: {e}")
                        
                    elif event_type == kCGEventKeyUp:
                        # Get key code and character
                        keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
                        
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
                        modifiers = parse_modifier_flags(flags)
                        
                        # Add key name if available
                        key_name = KEY_CODE_MAP.get(keycode, "")
                        
                        # Create the UI event
                        key_event = UIEvent(
                            "key_release",
                            time.time(),
                            keycode=keycode,
                            character=char,
                            key_name=key_name,
                            modifiers=modifiers
                        )
                        
                        # Call the callback
                        self.on_event_callback(key_event)
                        
                        # Log at debug level
                        key_display = char or key_name or f"keycode {keycode}"
                        logger.debug(f"Key release: {key_display}")
                        
                    elif event_type == kCGEventFlagsChanged:
                        # Get flags value
                        flags = CGEventGetFlags(event)
                        new_modifier_state = parse_modifier_flags(flags)
                        
                        # Check which modifier changed
                        changed_modifiers = {}
                        for modifier, state in new_modifier_state.items():
                            if self.modifier_state.get(modifier) != state:
                                changed_modifiers[modifier] = state
                        
                        # Update stored state
                        self.modifier_state = new_modifier_state
                        
                        if changed_modifiers:
                            # Create the UI event
                            mod_event = UIEvent(
                                "modifier_change",
                                time.time(),
                                changes=changed_modifiers,
                                state=new_modifier_state
                            )
                            
                            # Call the callback
                            self.on_event_callback(mod_event)
                            
                            # Format a clear message showing which modifiers changed
                            mod_changes = []
                            for mod, state in changed_modifiers.items():
                                mod_changes.append(f"{mod.upper()} {state and 'PRESSED' or 'RELEASED'}")
                            
                            logger.info(f"MODIFIER KEYS: {' | '.join(mod_changes)}")
                    
                except Exception as e:
                    logger.error(f"Error in keyboard event callback: {e}")
                
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
            tap = CGEventTapCreate(
                kCGSessionEventTap,       # Tap at session level
                kCGHeadInsertEventTap,    # Insert at the beginning of event processing
                kCGEventTapOptionDefault, # Default options
                event_mask,               # Events to listen for
                callback_function,        # Callback function
                None                      # User data (null in our case)
            )
            
            if tap is None:
                logger.error("Failed to create event tap. Make sure the app has the required permissions.")
                return False
            
            # Create a run loop source
            runloop_source = CFMachPortCreateRunLoopSource(None, tap, 0)
            
            # Add source to the current run loop
            CFRunLoopAddSource(
                CFRunLoopGetCurrent(),
                runloop_source,
                kCFRunLoopCommonModes
            )
            
            # Enable the event tap
            CGEventTapEnable(tap, True)
            
            logger.info("Event tap for keyboard monitoring set up successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error setting up event tap: {e}")
            return False
    
    def setup_pynput_keyboard_monitoring(self):
        """Set up keyboard monitoring using pynput library."""
        try:
            from pynput import keyboard
            logger.info("Setting up keyboard monitoring using pynput")
            
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
                    
                    # Create the UI event
                    key_event = UIEvent(
                        "key_press",
                        time.time(),
                        key=key_name,
                        modifiers=self.modifier_state.copy()
                    )
                    
                    # Call the callback
                    self.on_event_callback(key_event)
                    
                    # Write to key log file
                    if self.key_log_file:
                        try:
                            timestamp = time.time()
                            mod_list = '+'.join(active_mods) if active_mods else ""
                            with open(self.key_log_file, 'a') as f:
                                f.write(f"{timestamp},key_press,{key_name},{mod_list}\n")
                        except Exception as e:
                            logger.error(f"Failed to write to key log file: {e}")
                    
                    # Log the event
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
                    
                    # Create the UI event
                    key_event = UIEvent(
                        "key_release",
                        time.time(),
                        key=key_name,
                        modifiers=self.modifier_state.copy()
                    )
                    
                    # Call the callback
                    self.on_event_callback(key_event)
                    
                    # Write to key log file
                    if self.key_log_file:
                        try:
                            with open(self.key_log_file, 'a') as f:
                                f.write(f"{time.time()},key_release,{key_name}\n")
                        except Exception as e:
                            logger.error(f"Failed to write to key log file: {e}")
                    
                    # Log at debug level
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
            logger.error(f"Failed to set up keyboard monitoring with pynput: {e}")
            return False
            
    def start(self):
        """Start keyboard monitoring."""
        if self.running:
            logger.warning("Keyboard monitoring is already running")
            return
        
        self.running = True
        
        # Try pynput first (more reliable)
        if self.setup_pynput_keyboard_monitoring():
            logger.info("Keyboard monitoring started with pynput")
            
            # Log for debugging
            try:
                with open("/tmp/keyboard_debug.log", "w") as f:
                    f.write(f"{time.time()}: Keyboard monitoring started using pynput\n")
            except:
                pass
        else:
            # Fall back to event tap
            logger.error("Failed to set up keyboard monitoring with pynput, trying CGEventTap...")
            if self.setup_event_tap():
                logger.info("Keyboard monitoring started with event tap")
            else:
                logger.error("All keyboard monitoring methods failed!")
    
    def stop(self):
        """Stop keyboard monitoring."""
        if not self.running:
            return
        
        self.running = False
        
        # Stop the pynput keyboard listener
        if self.keyboard_listener:
            try:
                self.keyboard_listener.stop()
                logger.info("Keyboard listener stopped")
            except Exception as e:
                logger.error(f"Error stopping keyboard listener: {e}")

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