"""
Key mapping utilities for macOS UI Monitoring.
This module provides constants and functions for working with macOS key codes.
"""

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

def parse_modifier_flags(flags):
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