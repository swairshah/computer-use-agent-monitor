#!/usr/bin/env python3
"""
Tests for app detection functionality in osmonitor.
"""

import pytest
import time
import subprocess
import os
import sys

# Add the repository root to the Python path to import osmonitor modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from osmonitor.core.app_detection import get_frontmost_app_info, run_apple_script, get_app_detailed_info

class MockMonitor:
    """Mock class to substitute for MacOSUIMonitor in tests."""
    
    def __init__(self):
        self.current_app_pid = None


@pytest.fixture
def mock_monitor():
    """Fixture providing a mock monitor instance."""
    return MockMonitor()


@pytest.fixture(scope="module")
def firefox_check():
    """Check if Firefox is installed and get the current frontmost app."""
    is_installed = _is_firefox_installed()
    original_app = _get_frontmost_app_name() if is_installed else None
    
    yield {"installed": is_installed, "original_app": original_app}
    
    # Restore original app after all tests in this module
    if original_app:
        _activate_app(original_app)
        time.sleep(1)


def _is_firefox_installed():
    """Check if Firefox is installed."""
    try:
        result = subprocess.run(
            ['osascript', '-e', 'exists application "Firefox"'], 
            capture_output=True, text=True, timeout=1.0
        )
        return result.stdout.strip() == "true"
    except Exception:
        return False


def _get_frontmost_app_name():
    """Get the name of the currently frontmost app."""
    script = """
    tell application "System Events"
        set frontApp to first application process whose frontmost is true
        return name of frontApp
    end tell
    """
    try:
        result = subprocess.run(
            ['osascript', '-e', script], 
            capture_output=True, text=True, timeout=1.0
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def _activate_app(app_name):
    """Activate an application by name."""
    script = f"""
    tell application "{app_name}"
        activate
    end tell
    """
    try:
        subprocess.run(
            ['osascript', '-e', script], 
            capture_output=True, text=True, timeout=1.0
        )
    except Exception as e:
        print(f"Error activating app {app_name}: {e}")


def test_run_apple_script(mock_monitor):
    """Test the run_apple_script function."""
    script = 'return "test"'
    result = run_apple_script(mock_monitor, script)
    assert result == "test"


def test_firefox_detection(mock_monitor, firefox_check):
    """Test that Firefox is correctly detected when it's the frontmost app."""
    if not firefox_check["installed"]:
        pytest.skip("Firefox is not installed")
    
    # Activate Firefox
    _activate_app("Firefox")
    # Wait for Firefox to become frontmost
    time.sleep(2)
    
    # Get the frontmost app info
    app_info = get_frontmost_app_info(mock_monitor)
    detailed_info = get_app_detailed_info(mock_monitor, app_info)
    print(app_info)
    print(detailed_info)
    
    # Verify that Firefox was detected
    assert app_info is not None
    assert app_info.get("name").lower() == "firefox"
    assert app_info.get("pid") is not None
    assert app_info.get("method") is not None
    
    # Print debugging info
    print(f"Detected app info: {app_info}")
