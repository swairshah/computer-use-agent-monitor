"""
Application detection logic for macOS UI Monitoring.
This module handles detection of frontmost applications and windows.
"""

import logging
import subprocess
import AppKit

logger = logging.getLogger(__name__)

def get_frontmost_app_info(self_obj):
    """Get information about the frontmost application using multiple methods.
    
    Args:
        self_obj: The MacOSUIMonitor instance
        
    Returns:
        dict: Information about the frontmost app, or None if not found
    """
    # Method 1: Using NSWorkspace
    try:
        workspace = AppKit.NSWorkspace.sharedWorkspace()
        frontmost_app = workspace.frontmostApplication()
        
        if frontmost_app:
            app_name = frontmost_app.localizedName()
            app_pid = frontmost_app.processIdentifier()
            bundle_id = frontmost_app.bundleIdentifier() or ""
            
            return {
                "name": app_name,
                "pid": app_pid,
                "bundle_id": bundle_id,
                "method": "NSWorkspace"
            }
    except Exception as e:
        logger.debug(f"NSWorkspace method failed: {e}")
    
    # Method 2: Using AppleScript
    script = """
    tell application "System Events"
        set frontApp to first application process whose frontmost is true
        set frontAppName to name of frontApp
        set frontAppPID to unix id of frontApp
        return frontAppName & ":" & frontAppPID
    end tell
    """
    result = run_apple_script(self_obj, script)
    if result and ":" in result:
        app_name, app_pid_str = result.split(":", 1)
        try:
            app_pid = int(app_pid_str.strip())
            return {
                "name": app_name.strip(),
                "pid": app_pid,
                "bundle_id": "",
                "method": "AppleScript"
            }
        except ValueError:
            logger.debug(f"Could not parse PID from AppleScript: {app_pid_str}")
    
    # Method 3: Try using 'lsappinfo' command
    try:
        result = subprocess.run(['lsappinfo', 'front'], capture_output=True, text=True, timeout=1.0)
        if result.returncode == 0:
            output = result.stdout
            # Parse the ASN from the output
            asn = None
            for line in output.splitlines():
                if "ASN:" in line:
                    asn = line.split("ASN:")[1].strip()
                    break
            
            if asn:
                # Get app info using the ASN
                info_result = subprocess.run(['lsappinfo', 'info', asn], 
                                            capture_output=True, text=True, timeout=1.0)
                if info_result.returncode == 0:
                    info_output = info_result.stdout
                    app_name = None
                    app_pid = None
                    
                    for line in info_output.splitlines():
                        if "display name" in line.lower():
                            app_name = line.split('=')[1].strip(' "')
                        elif "pid" in line.lower():
                            try:
                                app_pid = int(line.split('=')[1].strip())
                            except ValueError:
                                pass
                    
                    if app_name and app_pid:
                        return {
                            "name": app_name,
                            "pid": app_pid,
                            "bundle_id": "",
                            "method": "lsappinfo"
                        }
    except Exception as e:
        logger.debug(f"lsappinfo method failed: {e}")
    
    # Method 4: Use ps command to get active GUI apps
    try:
        # Get list of foreground GUI apps (those with a window)
        ps_result = subprocess.run(['ps', '-axco', 'pid,command'], 
                                 capture_output=True, text=True, timeout=1.0)
        if ps_result.returncode == 0:
            lines = ps_result.stdout.strip().split('\n')
            gui_apps = []
            
            for line in lines[1:]:  # Skip header line
                parts = line.strip().split(None, 1)
                if len(parts) == 2:
                    try:
                        pid = int(parts[0])
                        command = parts[1]
                        
                        # Filter out obvious background processes
                        if (not command.endswith('helper') and
                            not command.startswith('com.apple.') and
                            not command == 'launchd' and
                            not command == 'kernel_task'):
                            gui_apps.append((pid, command))
                    except ValueError:
                        continue
            
            # Use process with lowest PID as a fallback
            if gui_apps:
                gui_apps.sort()  # Sort by PID
                pid, command = gui_apps[0]
                return {
                    "name": command,
                    "pid": pid,
                    "bundle_id": "",
                    "method": "ps"
                }
    except Exception as e:
        logger.debug(f"ps method failed: {e}")
    
    # If we still have a current_app_pid, use that as last resort
    if self_obj.current_app_pid:
        return {
            "name": "Unknown App",
            "pid": self_obj.current_app_pid,
            "bundle_id": "",
            "method": "fallback"
        }
    
    return None

def get_windows_for_app(self_obj, app_pid):
    """Get windows for an application using AppleScript.
    
    Args:
        self_obj: The MacOSUIMonitor instance
        app_pid: The process ID of the application
        
    Returns:
        list: List of window names
    """
    try:
        # Try using direct System Events query
        script = f"""
        tell application "System Events"
            set appProcess to first process whose unix id is {app_pid}
            set windowNames to name of windows of appProcess
            return windowNames
        end tell
        """
        result = run_apple_script(self_obj, script)
        
        if result:
            # Parse output - typically a comma-separated list
            windows = [w.strip() for w in result.split(',')]
            if windows and windows[0]:
                return windows
        
        # Try alternate script for getting window titles
        script = f"""
        tell application "System Events"
            set frontApp to first process whose unix id is {app_pid}
            set windowList to {{}}
            repeat with w in windows of frontApp
                copy name of w to end of windowList
            end repeat
            return windowList
        end tell
        """
        result = run_apple_script(self_obj, script)
        
        if result:
            windows = [w.strip() for w in result.split(',')]
            return [w for w in windows if w]
        
        return []
    except Exception as e:
        logger.debug(f"Error getting windows for app with PID {app_pid}: {e}")
        return []

def run_apple_script(self_obj, script):
    """Run an AppleScript and return the result.
    
    Args:
        self_obj: The MacOSUIMonitor instance
        script: The AppleScript to run
        
    Returns:
        str: The result of the AppleScript, or None if it failed
    """
    try:
        result = subprocess.run(['osascript', '-e', script], 
                               capture_output=True, text=True, timeout=1.0)
        if result.returncode == 0:
            return result.stdout.strip()
        else:
            logger.debug(f"AppleScript error: {result.stderr}")
            return None
    except Exception as e:
        logger.debug(f"Error running AppleScript: {e}")
        return None
