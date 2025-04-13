import os
import subprocess
import json
import time
import argparse
from datetime import datetime
from pynput import mouse, keyboard
from PIL import ImageGrab, Image
import sys

# Import accessibility permission checker
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from osmonitor.utils.accessibility import check_accessibility_permissions

# Default paths
SAVE_DIR = "./screenshots"
EVENT_LOG_FILE = "./timeline.json"

# Parse command line arguments
def parse_args():
    parser = argparse.ArgumentParser(description="Monitor UI events and take screenshots")
    parser.add_argument('--save-dir', type=str, default=SAVE_DIR, 
                       help="Directory to save screenshots (default: ./screenshots)")
    parser.add_argument('--log-file', type=str, default=EVENT_LOG_FILE,
                       help="File to save event log (default: ./timeline.json)")
    return parser.parse_args()

# Get command line arguments
args = parse_args()
SAVE_DIR = args.save_dir
EVENT_LOG_FILE = args.log_file

# Create screenshots directory and empty log file
os.makedirs(SAVE_DIR, exist_ok=True)
print(f"Screenshots will be saved to: {SAVE_DIR}")
print(f"Events will be logged to: {EVENT_LOG_FILE}")

with open(EVENT_LOG_FILE, "w") as f:
    f.write("")

key_buffer = ""

def get_screen_dimensions():
    # Get screen dimensions using PIL instead of tkinter
    img = ImageGrab.grab()
    return img.width, img.height

# Request accessibility permissions once at startup
has_permissions = check_accessibility_permissions(show_prompt=True)
if not has_permissions:
    print("⚠️  Please grant accessibility permissions in System Preferences")
    print("   Go to System Preferences > Security & Privacy > Privacy > Accessibility")
    print("   Add and enable your terminal application (e.g., Terminal, iTerm2, or Ghostty)")
    print("   This is required for monitoring foreground applications")
    input("Press Enter to continue after granting permissions...")

SCREEN_WIDTH, SCREEN_HEIGHT = get_screen_dimensions()

APPLE_SCRIPT = """
tell application "System Events"
    set frontApp to first process whose frontmost is true
    set appName to name of frontApp
    try
        set windowTitle to ""
        if exists (first window of frontApp) then
            set windowTitle to title of first window of frontApp
        end if
        return {appName, windowTitle}
    on error
        return {appName, "No Window"}
    end try
end tell
"""

DETAILED_APP_INFO_SCRIPT = """
tell application "System Events"
    set frontApp to first process whose unix id is {pid}
    set frontWindow to first window of frontApp
    return {{
        name of frontWindow,
        title of frontWindow,
        description of frontWindow,
        value of frontWindow,
        size of frontWindow,
        position of frontWindow
    }}
end tell
"""

def get_frontmost_app_info():
    try:
        script = f"osascript -e '{APPLE_SCRIPT}'"
        result = subprocess.run(script, shell=True, capture_output=True, text=True)
        if result.returncode == 0:
            parts = result.stdout.strip().split(",")
            return {
                "app_name": parts[0].strip(),
                "window_title": ",".join(parts[1:]).strip() if len(parts) > 1 else "No Window",
                "raw_output": result.stdout.strip()
            }
        print(f"AppleScript error: {result.stderr}")
        print(f"Return code: {result.returncode}")
    except Exception as e:
        print(f"Error getting app info: {e}")
    return {"app_name": "Unknown", "window_title": "Unknown", "raw_output": ""}

def log_event(event_type, additional_info=None):
    timestamp = time.time()
    app_info = get_frontmost_app_info()

    event = {
        "timestamp": timestamp,
        "event_type": event_type,
        "app_info": app_info,
        "element_title": "",
        "element_role": "",
        "position": normalize_coordinates(*mouse.Controller().position)
    }

    if additional_info:
        event.update(additional_info)

    with open(EVENT_LOG_FILE, "a") as log_file:
        log_file.write(json.dumps(event) + "\n")

def take_screenshot(event_type):
    timestamp_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")
    filename = f"{event_type}_{timestamp_str}.png"
    filepath = os.path.join(SAVE_DIR, filename)

    screenshot = ImageGrab.grab()
    screenshot.save(filepath)

    log_event(event_type, {"screenshot_path": filepath})
    print(f"[{timestamp_str}] {event_type} | Saved screenshot: {filepath}")

def log_keystroke(key):
    global key_buffer
    try:
        if hasattr(key, 'char') and key.char is not None:
            key_buffer += key.char
            x, y = mouse.Controller().position
            position = normalize_coordinates(x, y)
            log_event("text_entry", {
                "character": key.char,
                "current_buffer": key_buffer,
                "position": position,
                "type": "character"
            })
        elif key == keyboard.Key.enter:
            if key_buffer:
                x, y = mouse.Controller().position
                position = normalize_coordinates(x, y)
                log_event("text_entry", {
                    "character": "[ENTER]",
                    "current_buffer": key_buffer,
                    "position": position,
                    "type": "enter"
                })
                key_buffer = ""
        elif key == keyboard.Key.space:
            key_buffer += " "
            x, y = mouse.Controller().position
            position = normalize_coordinates(x, y)
            log_event("text_entry", {
                "character": "[SPACE]",
                "current_buffer": key_buffer,
                "position": position,
                "type": "space"
            })
        elif key == keyboard.Key.backspace and key_buffer:
            deleted_char = key_buffer[-1]
            key_buffer = key_buffer[:-1]
            x, y = mouse.Controller().position
            position = normalize_coordinates(x, y)
            log_event("text_entry", {
                "character": "[BACKSPACE]",
                "deleted_character": deleted_char,
                "current_buffer": key_buffer,
                "position": position,
                "type": "backspace"
            })
    except AttributeError:
        pass

def normalize_coordinates(x, y):
    """Normalize coordinates to 0-1 range based on screen dimensions"""
    return {
        "raw": {"x": x, "y": y},
        "normalized": {"x": round(x / SCREEN_WIDTH, 4), "y": round(y / SCREEN_HEIGHT, 4)}
    }

def on_click(x, y, button, pressed):
    global key_buffer
    if pressed:
        position = normalize_coordinates(x, y)
        take_screenshot("mouse_click")
        
        if key_buffer:
            log_event("text_entry", {"text": key_buffer, "trigger": "mouse_click", "position": position})
            key_buffer = ""
            
        log_event("mouse_click", {"position": position})

def on_scroll(x, y, dx, dy):
    position = normalize_coordinates(x, y)
    take_screenshot("scroll")
    log_event("scroll", {"position": position, "scroll_dx": dx, "scroll_dy": dy})

def on_press(key):
    x, y = mouse.Controller().position
    position = normalize_coordinates(x, y)
    log_keystroke(key)  # Call this first to log the character
    take_screenshot("key_press")  # Then take screenshot
    log_event("key_press", {"position": position}) 

mouse_listener = mouse.Listener(on_click=on_click, on_scroll=on_scroll)
keyboard_listener = keyboard.Listener(on_press=on_press)

mouse_listener.start()
keyboard_listener.start()

print(f"Monitoring events. Press Ctrl+C to stop.")
print(f"Screen dimensions: {SCREEN_WIDTH}x{SCREEN_HEIGHT}")

try:
    mouse_listener.join()
    keyboard_listener.join()
except KeyboardInterrupt:
    print("Monitoring stopped.")
    mouse_listener.stop()
    keyboard_listener.stop()
