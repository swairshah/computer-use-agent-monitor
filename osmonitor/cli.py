"""
Command line interface for macOS UI Monitoring.
This module provides the command line entry point for the UI monitor.
"""

import argparse
import sys
import time
import os
import logging
from logging.handlers import RotatingFileHandler

from osmonitor.core.monitor import MacOSUIMonitor
from osmonitor.core.elements import ElementInfo
from osmonitor.core.keyboard_monitor import fallback_keyboard_logging
from osmonitor.utils.accessibility import check_accessibility_permissions


def setup_argparse():
    """Set up command line argument parsing."""
    parser = argparse.ArgumentParser(
        description="macOS UI Monitor - Track UI state, events, and interactions",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    parser.add_argument(
        "--polling-interval", 
        type=float, 
        default=0.2,
        help="Interval in seconds between UI state polls"
    )
    
    parser.add_argument(
        "--history-size", 
        type=int, 
        default=1000,
        help="Maximum number of events to keep in history"
    )
    
    parser.add_argument(
        "--debug", 
        action="store_true", 
        help="Enable debug logging"
    )
    
    parser.add_argument(
        "--quiet", 
        action="store_true", 
        help="Reduce logging to warnings and errors only"
    )
    
    parser.add_argument(
        "--output-file", 
        type=str,
        help="Path to file where events should be saved as JSON lines"
    )
    
    parser.add_argument(
        "--verbose", 
        action="store_true",
        help="Show detailed app state information"
    )
    
    parser.add_argument(
        "--screenshots", 
        action="store_true",
        default=True,  # Enable by default
        help="Take screenshots on click events (enabled by default)"
    )
    
    parser.add_argument(
        "--screenshot-dir", 
        type=str,
        default="./screenshots",
        help="Directory to save screenshots in"
    )
    
    parser.add_argument(
        "--dump-attributes", 
        action="store_true",
        help="Dump all raw accessibility attributes for debugging"
    )
    
    parser.add_argument(
        "--log-events", 
        choices=["all", "clicks", "keys", "scroll", "modifiers", "selections"],
        nargs="+",
        default=["all"],
        help="Specify which events to log (default: all)"
    )
    
    parser.add_argument(
        "--log-file", 
        type=str,
        help="Path to a log file where all events will be saved (separate from output file)"
    )
    
    parser.add_argument(
        "--key-log-file", 
        type=str,
        help="Path to a simplified CSV log file that will contain ONLY keyboard events"
    )
    
    parser.add_argument(
        "--timeline-file",
        type=str,
        default="./timeline.json",
        help="Path to a consolidated timeline file containing all events in chronological order (default: ./timeline.json)"
    )
    
    parser.add_argument(
        "--timeline-format",
        choices=["json", "csv"],
        default="json",
        help="Format for the timeline file (default: json)"
    )
    
    parser.add_argument(
        "--fallback-keyboard-logging",
        action="store_true",
        help="Use fallback terminal-based keyboard logging method if the main method fails"
    )
    
    parser.add_argument(
        "--monitor-text-selection",
        action="store_true",
        default=True,  # Enable by default
        help="Monitor and log text selections in applications (enabled by default)"
    )
    
    parser.add_argument(
        "--selection-interval", 
        type=float, 
        default=1.0,
        help="Interval in seconds between checking for text selections"
    )
    
    parser.add_argument(
        "--log-file-size", 
        type=int,
        default=10485760,  # 10MB
        help="Maximum size of log file in bytes before rotation"
    )
    
    parser.add_argument(
        "--log-file-backups", 
        type=int,
        default=3,
        help="Number of log file backups to keep when rotating"
    )
    
    # Register completions if argcomplete is installed
    try:
        import argcomplete
        argcomplete.autocomplete(parser)
    except ImportError:
        pass
    
    return parser


def main(argv=None):
    """Main entry point for the UI monitor."""
    parser = setup_argparse()
    args = parser.parse_args(argv)
    
    # Set up logging - we need at least INFO level to see events
    log_level = logging.DEBUG if args.debug else (logging.WARNING if args.quiet else logging.INFO)
    
    # First reset root handlers in case basicConfig was called elsewhere
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Create a custom formatter
    log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # Configure root logger first with base level
    root_logger.setLevel(logging.DEBUG)  # Allow everything through at root level
    
    # Set up console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)
    console_handler.setLevel(log_level)
    root_logger.addHandler(console_handler)
    
    # Set up file handler if log file is specified
    if args.log_file:
        # Create log directory if it doesn't exist
        log_dir = os.path.dirname(os.path.abspath(args.log_file))
        os.makedirs(log_dir, exist_ok=True)
        
        # Create a rotating file handler
        file_handler = RotatingFileHandler(
            args.log_file, 
            maxBytes=args.log_file_size, 
            backupCount=args.log_file_backups,
            encoding='utf-8'
        )
        file_handler.setFormatter(log_formatter)
        # Always log at INFO level to file to ensure we capture keyboard events
        file_handler.setLevel(logging.INFO)
        root_logger.addHandler(file_handler)
        
        print(f"Logging events to file: {os.path.abspath(args.log_file)}")
    
    # Make sure our module logger is at least INFO level so events show up
    module_logger = logging.getLogger("osmonitor")
    module_logger.setLevel(logging.INFO if not args.quiet else log_level)
    logger = logging.getLogger(__name__)
    
    # Create output file directory if it doesn't exist
    if args.output_file:
        os.makedirs(os.path.dirname(os.path.abspath(args.output_file)), exist_ok=True)
    
    # Create screenshot directory if screenshots enabled
    screenshot_dir = None
    if args.screenshots:
        screenshot_dir = args.screenshot_dir
        
    # If dump-attributes is enabled, set global flag for ElementInfo
    if args.dump_attributes:
        # Monkeypatch the ElementInfo.to_dict method to include raw attributes
        original_to_dict = ElementInfo.to_dict
        
        def to_dict_with_raw_attrs(self):
            result = original_to_dict(self)
            # Add raw attributes
            result["_raw_attributes"] = {
                k: str(v) for k, v in self.raw_attributes.items()
            }
            return result
            
        ElementInfo.to_dict = to_dict_with_raw_attrs
        logger.info("Raw accessibility attributes will be included in element info")
    
    # Create a monitor to check if keyboard event tap will work
    event_tap_file = "/tmp/keyboard_debug.log"
    if os.path.exists(event_tap_file):
        os.remove(event_tap_file)
        
    # Create and start the monitor
    monitor = MacOSUIMonitor(
        history_size=args.history_size,
        polling_interval=args.polling_interval,
        log_level=log_level,
        output_file=args.output_file,
        screenshot_dir=screenshot_dir,
        take_screenshots=args.screenshots,
        key_log_file=args.key_log_file,
        timeline_file=args.timeline_file,
        timeline_format=args.timeline_format,
        monitor_text_selection=args.monitor_text_selection,
        selection_interval=args.selection_interval
    )
    
    # Check if fallback is needed after a brief delay to let event tap start
    if args.fallback_keyboard_logging:
        time.sleep(3)  # Wait for event tap to initialize
        
        # Check if keyboard events are being detected
        keyboard_working = False
        
        # Check if the debug file exists and contains evidence of working keyboard monitoring
        if os.path.exists(event_tap_file):
            with open(event_tap_file, "r") as f:
                content = f.read()
                if "Test event posted" in content and "EVENT TAP CREATED SUCCESSFULLY" in content:
                    keyboard_working = True
        
        if not keyboard_working:
            print("\n\n============================================================")
            print("WARNING: Keyboard event monitoring does not appear to be working")
            print("============================================================")
            print("This is likely because:")
            print("1. The app doesn't have proper accessibility permissions")
            print("2. You're running in a sandboxed environment that restricts access")
            print("\nStarting fallback keyboard logging method...\n")
            
            # Stop the monitor before switching to fallback
            monitor.stop()
            # Switch to fallback method
            fallback_keyboard_logging()
            return 1  # Exit with code 1
    
    # Example callback for click events
    def on_click(event):
        details = []
        
        if "button" in event.details:
            details.append(f"Button: {event.details['button']}")
        
        if "position" in event.details:
            pos = event.details["position"]
            details.append(f"Position: ({pos['x']:.1f}, {pos['y']:.1f})")
        
        if "element" in event.details:
            element = event.details["element"]
            # Get the most important element info
            element_info = []
            
            if "title" in element and element["title"]:
                element_info.append(f'"{element["title"]}"')
                
            if "role" in element:
                if "role_description" in element:
                    element_info.append(element["role_description"])
                else:
                    element_info.append(element["role"])
                    
            if "subrole" in element:
                element_info.append(f"subrole:{element['subrole']}")
                
            if "status" in element:
                status = element["status"]
                if status.get("selected"):
                    element_info.append("selected")
                if status.get("focused"):
                    element_info.append("focused")
            
            if element_info:
                details.append(f"Element: {' '.join(element_info)}")
        
        if "screenshot" in event.details:
            details.append(f"Screenshot: {os.path.basename(event.details['screenshot'])}")
        
        # Print the basic details first
        if details:
            print(f"Click detected: {', '.join(details)}")
        
        # If debug mode or dump attributes is enabled, print raw attributes
        if args.debug or args.dump_attributes:
            if "element" in event.details and "_raw_attributes" in event.details["element"]:
                print("\nAccessibility Attributes:")
                raw_attrs = event.details["element"]["_raw_attributes"]
                for key in sorted(raw_attrs.keys()):
                    value = raw_attrs[key]
                    # For long values, truncate them
                    if len(str(value)) > 50:
                        value = f"{str(value)[:47]}..."
                    print(f"  {key}: {value}")
    
    # Example callback for keyboard events
    def on_key_press(event):
        details = []
        
        # First try character, then key_name, then keycode
        if "character" in event.details and event.details["character"]:
            details.append(f"Key: '{event.details['character']}'")
        elif "key_name" in event.details and event.details["key_name"]:
            details.append(f"Key: {event.details['key_name']}")
        elif "keycode" in event.details:
            details.append(f"Keycode: {event.details['keycode']}")
            
        if "modifiers" in event.details:
            mods = event.details["modifiers"]
            active_mods = [name for name, active in mods.items() if active]
            if active_mods:
                details.append(f"Modifiers: {'+'.join(active_mods)}")
        
        if details:
            print(f"Key press: {', '.join(details)}")
            
    # Example callback for key release events
    def on_key_release(event):
        if args.debug:  # Only show releases in debug mode to reduce verbosity
            # First try character, then key_name, then keycode
            if "character" in event.details and event.details["character"]:
                print(f"Key release: '{event.details['character']}'")
            elif "key_name" in event.details and event.details["key_name"]:
                print(f"Key release: {event.details['key_name']}")
            elif "keycode" in event.details:
                print(f"Key release: keycode {event.details['keycode']}")
    
    # Example callback for modifier key changes
    def on_modifier_change(event):
        if "changes" in event.details:
            changes = event.details["changes"]
            mod_changes = []
            for mod, state in changes.items():
                mod_changes.append(f"{mod} {'pressed' if state else 'released'}")
            
            if mod_changes:
                print(f"Modifier keys: {', '.join(mod_changes)}")
    
    # Example callback for scroll events
    def on_scroll(event):
        details = []
        
        if "delta_x" in event.details and event.details["delta_x"] != 0:
            details.append(f"Horizontal: {event.details['delta_x']}")
            
        if "delta_y" in event.details and event.details["delta_y"] != 0:
            details.append(f"Vertical: {event.details['delta_y']}")
            
        if "position" in event.details:
            pos = event.details["position"]
            details.append(f"Position: ({pos['x']:.1f}, {pos['y']:.1f})")
            
        if details:
            print(f"Scroll: {', '.join(details)}")
            
    # Example callback for text selection events
    def on_text_selection(event):
        if "text" in event.details:
            text = event.details["text"]
            source = event.details.get("source", "unknown")
            app_name = event.details.get("app_name", "Unknown App")
            
            # Truncate text for display if too long
            if len(text) > 100:
                display_text = text[:97] + "..."
            else:
                display_text = text
                
            print(f"Text Selected in {app_name}: \"{display_text}\"")
            
            # Print metadata if in verbose mode
            if args.verbose:
                print(f"  Source: {source}")
                print(f"  Length: {len(text)} characters")
    
    # Register callbacks based on log events selection
    log_events = args.log_events
    
    # If "all" is in the list, include all events
    if "all" in log_events:
        log_events = ["clicks", "keys", "modifiers", "scroll", "selections"]
    
    # Register appropriate callbacks
    if "clicks" in log_events:
        monitor.add_callback("click", on_click)
        
    if "keys" in log_events:
        monitor.add_callback("key_press", on_key_press)
        monitor.add_callback("key_release", on_key_release)
        
    if "modifiers" in log_events:
        monitor.add_callback("modifier_change", on_modifier_change)
        
    if "scroll" in log_events:
        monitor.add_callback("scroll", on_scroll)
        
    if "selections" in log_events:
        monitor.add_callback("text_selection", on_text_selection)
    
    try:
        # Start monitoring
        monitor.start()
        print("UI Monitor running. Press Ctrl+C to stop.")
        
        # enabled features
        print("\nEnabled features:")
        if "clicks" in log_events:
            print("- Click events will be logged")
        if "keys" in log_events:
            print("- Keyboard events will be logged")
        if "modifiers" in log_events:
            print("- Modifier key events will be logged")
        if "scroll" in log_events:
            print("- Scroll events will be logged")
        if "selections" in log_events:
            print(f"- Text selections will be logged (checking every {args.selection_interval:.1f}s)")
        
        # Screenshots are enabled by default
        print(f"- Screenshots will be saved to: {os.path.abspath(args.screenshot_dir)}")
        if args.log_file:
            print(f"- All events will be saved to log file: {os.path.abspath(args.log_file)}")
            print("  (This file will contain complete keyboard event logs)")
        if args.key_log_file:
            print(f"- Keyboard events will be saved to CSV file: {os.path.abspath(args.key_log_file)}")
            print("  (This is a simpler format that is guaranteed to capture all keystrokes)")
        
        print(f"- Consolidated timeline will be saved as {args.timeline_format.upper()} to: {os.path.abspath(args.timeline_file)}")
        print("  (This file will contain all events in chronological order with context)")
        
        if args.output_file:
            print(f"- Raw events will be saved as JSON lines to: {os.path.abspath(args.output_file)}")
        
        # Keep the main thread alive
        while True:
            time.sleep(1)
            
            # Periodically print current state
            if monitor.running:
                current_state = monitor.get_current_state()
                app_name = current_state.get("current_app", {}).get("name", "None")
                app_method = current_state.get("current_app", {}).get("method", "Unknown")
                window_title = current_state.get("current_window", {}).get("title", "None")
                mouse_pos = current_state.get("mouse_position", {})
                
                if args.verbose:
                    print(f"App: {app_name} ({app_method}) | Window: {window_title} | Mouse: {mouse_pos}")
                else:
                    print(f"App: {app_name} | Window: {window_title}")
    
    except KeyboardInterrupt:
        print("Stopping UI Monitor...")
    finally:
        monitor.stop()
    
    return 0  


if __name__ == "__main__":
    sys.exit(main())
