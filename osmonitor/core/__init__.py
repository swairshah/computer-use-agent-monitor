"""Core functionality for macOS UI monitoring."""

from osmonitor.core.monitor import MacOSUIMonitor
from osmonitor.core.elements import ElementInfo, ElementAttributes, WindowState, WindowIdentifier, UIFrame
from osmonitor.core.events import UIEvent

from osmonitor.core.app_detection import get_frontmost_app_info, get_windows_for_app, run_apple_script
from osmonitor.core.ui_traversal import traverse_ui_elements, get_ui_data_via_applescript, write_to_pipe
from osmonitor.core.event_handling import add_event, log_ui_event, notify_callbacks, write_to_timeline
