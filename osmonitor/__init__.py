"""macOS UI Monitoring package."""

# Import the main classes to make them available at the package level
from osmonitor.core.monitor import MacOSUIMonitor
from osmonitor.core.events import UIEvent
from osmonitor.core.elements import ElementInfo

# Make the main function available at the package level
from osmonitor.cli import main
