#!/usr/bin/env python3
"""
menu bar app for OSMonitor.
"""
import os
import sys
import signal
import subprocess
import threading
from pathlib import Path
import rumps

HOME = Path.home()
BASE_DIR = HOME / ".osmonitor"
SCREENSHOTS_DIR = BASE_DIR / "screenshots"
LOG_FILE = BASE_DIR / "timeline.json"

BASE_DIR.mkdir(exist_ok=True)
SCREENSHOTS_DIR.mkdir(exist_ok=True)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ICON_INACTIVE = os.path.join(SCRIPT_DIR, "icons", "inactive.png")  
ICON_ACTIVE = os.path.join(SCRIPT_DIR, "icons", "active.png")      

USE_EMOJI_FALLBACK = not (os.path.exists(ICON_INACTIVE) and os.path.exists(ICON_ACTIVE))

class CustomStatusBarApp(rumps.App):
    def __init__(self):
        icon = "📷" if USE_EMOJI_FALLBACK else ICON_INACTIVE
        
        super(CustomStatusBarApp, self).__init__(
            name="OSMonitor",
            title=icon,  
            icon=None if USE_EMOJI_FALLBACK else icon,
            quit_button="Quit",
            template=True,  
        )
        
        self.monitor_process = None
        self.is_recording = False
        
        self.status_display = rumps.MenuItem("Status: Idle")
        self.status_display.set_callback(None)  # Make it non-clickable
        
        self.menu = [
            self.status_display,
            None,  # Separator
            rumps.MenuItem("Toggle Recording", callback=self.toggle_recording),
            rumps.MenuItem("Open Data Folder", callback=self.open_data_folder),
            None,  # Separator
        ]
    
    @rumps.clicked('OSMonitor')
    def clicked(self, _):
        """This handles clicks on the menu bar icon"""
        print("Icon clicked! Toggling recording...") 
        self.toggle_recording(None)
    
    def toggle_recording(self, sender):
        if self.is_recording:
            # Stop recording
            if self.monitor_process:
                os.kill(self.monitor_process.pid, signal.SIGINT)
                self.monitor_process = None
            
            self.is_recording = False
            
            # Update status in the dropdown menu
            self.status_display.title = "Status: Idle"
            
            # Update menu bar icon
            if USE_EMOJI_FALLBACK:
                self.title = "📷"
            else:
                self.icon = ICON_INACTIVE
            
            # Skip notification - print to console instead
            print(f"Recording stopped. Data saved to {BASE_DIR}")
        else:
            # Start recording
            self.is_recording = True
            
            # Update status in the dropdown menu
            self.status_display.title = "Status: Recording"
            
            # Update menu bar icon
            if USE_EMOJI_FALLBACK:
                self.title = "📸" 
            else:
                self.icon = ICON_ACTIVE
            
            def run_monitor():
                # Get path to monitor.py script
                script_dir = os.path.dirname(os.path.abspath(__file__))
                monitor_script = os.path.join(script_dir, "monitor.py")
                
                # Use the Python from the virtual environment
                venv_python = os.path.join(SCRIPT_DIR, ".venv", "bin", "python")
                if not os.path.exists(venv_python):
                    print(f"Virtual environment Python not found at {venv_python}")
                    print("Falling back to current Python interpreter")
                    python_exe = sys.executable
                else:
                    python_exe = venv_python
                
                # Run monitor with paths to save files
                cmd = [
                    python_exe,
                    monitor_script,
                    "--save-dir", str(SCREENSHOTS_DIR),
                    "--log-file", str(LOG_FILE)
                ]
                
                print(f"Starting monitor with command: {' '.join(cmd)}")
                self.monitor_process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                
                def log_output():
                    try:
                        stdout, stderr = self.monitor_process.communicate()
                        if stdout:
                            print(f"Monitor stdout: {stdout.decode()}")
                        if stderr:
                            print(f"Monitor stderr: {stderr.decode()}")
                    except Exception as e:
                        print(f"Error during monitor communication: {e}")
                
                # Start output logging in a separate thread
                output_thread = threading.Thread(target=log_output)
                output_thread.daemon = True
                output_thread.start()
            
            # Run in background thread
            thread = threading.Thread(target=run_monitor)
            thread.daemon = True
            thread.start()
            
            # Skip notification - print to console instead
            print(f"Recording started. Saving to {BASE_DIR}")
    
    def open_data_folder(self, _):
        subprocess.run(["open", str(BASE_DIR)])

if __name__ == "__main__":
    app = CustomStatusBarApp()
    print(f"OSMonitor starting. Data will be saved to {BASE_DIR}")
    print(f"Using custom icons: {'No (emoji fallback)' if USE_EMOJI_FALLBACK else 'Yes'}")
    print("Click directly on the icon to toggle recording on/off")
    app.run()
