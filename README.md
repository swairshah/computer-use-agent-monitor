# Computer Use Agent Monitor

A tool for monitoring and logging UI events on macOS, including keyboard input, mouse clicks, window changes, and text selections.

- Monitor keyboard events, mouse clicks, and scrolling
- Track active applications and window changes
- Capture screenshots on click events
- Record text selections
- Timeline generation in JSON or CSV format
- Detailed logging options

## Installation

```bash
# Install dependencies
pip install -r requirements.txt

# Install the package in development mode
pip install -e .
```

## Usage

```bash
# Basic usage
osmonitor

# Enable debug logging
osmonitor --debug

# Customize screenshot directory
osmonitor --screenshot-dir /path/to/screenshots

# Save timeline to custom location
osmonitor --timeline-file /path/to/timeline.json

# Output timeline in CSV format
osmonitor --timeline-format csv
```

## Project Structure

```
osmonitor/
├── __init__.py         # Package exports
├── cli.py              # Command line interface
├── core/
│   ├── __init__.py
│   ├── elements.py     # UI element handling
│   ├── events.py       # Event classes
│   ├── keyboard_monitor.py # Keyboard monitoring
│   ├── monitor.py      # Main monitor class
│   ├── mouse_monitor.py # Mouse monitoring
│   ├── screenshot.py   # Screenshot utilities
│   └── text_selection.py # Text selection monitoring
└── utils/
    ├── __init__.py
    ├── accessibility.py # Accessibility utilities
    └── key_mapping.py   # Keyboard mapping utilities
```

## Requirements

- macOS 10.15 or later
- Python 3.8 or later
- PyObjC
- pynput

## Permissions

This tool requires accessibility permissions to function properly. 
Give the Accessibility permissions to the terminal you invoke the tool from.
