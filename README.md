# Computer Use Agent Monitor

A tool for monitoring and logging UI events on macOS, including keyboard input, mouse clicks, window changes, and text selections.

- Monitor keyboard events, mouse clicks, and scrolling
- Track active applications and window changes
- Capture screenshots on click events
- Record text selections
- Timeline generation in JSON or CSV format
- Detailed logging options

## Features

1. **Activity Timeline**: Records UI events in chronological order with timestamps

2. **Screenshot Capture**: Takes screenshots when clicks, keystrokes, or scroll events occur

3. **Activity Summarization**: Uses Pydantic AI agents to analyze computer use patterns and generate summaries

4. **Screenshot Analysis**: Leverages vision-capable AI models to extract information from screenshots

5. **Application Usage Tracking**: Monitors which applications are active and for how long

## TODOs

1. **Timeline Condensing**: Detect typing sequences and condense them into a single 'typed_text' event rather than logging each keystroke separately
   
2. **Screenshot Element Extraction**: Crop areas around the mouse position to capture the most important UI element (button, tab, text field, etc.)

3. **OCR Support**: Add optical character recognition capabilities for extracting text from captured screenshots

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

## Requirements

- macOS 10.15 or later
- Python 3.8 or later
- PyObjC
- pynput

## macOS Permissions Required

This tool requires macOS accessibility permissions to function properly:

### One-time Setup (Recommended)

1. Go to **System Preferences** > **Security & Privacy** > **Privacy** > **Accessibility**
2. Add your terminal application (Terminal, iTerm2, Ghostty, etc.) to the list
3. Make sure the checkbox next to your terminal is enabled

This one-time setup will prevent multiple permission prompts when running the monitor.

### Why Does This Need Permissions?

The monitor uses macOS Accessibility and AppleScript APIs to:
- Detect the foreground application and window title
- Capture keyboard and mouse events
- Take screenshots when events occur

Without these permissions, you'll get permission prompts for each application the monitor interacts with.
