"""
Command line interface for macOS UI Monitoring.
provides the command line entry point for the UI monitor.
"""

import sys
import os
import importlib.util

def main(argv=None):
    """Main entry point for the UI monitor."""
    monitor_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'monitor.py')
    spec = importlib.util.spec_from_file_location('monitor', monitor_path)
    monitor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(monitor)
    
    return 0
