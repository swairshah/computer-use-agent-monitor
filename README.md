# Computer Use Agent Monitor

A tool for monitoring and logging UI events on macOS, including keyboard input, mouse clicks, window changes, and text selections.

- Monitor keyboard events, mouse clicks, and scrolling
- Track active applications and window changes
- Capture screenshots on click events
- Record text selections
- Timeline generation in JSON or CSV format

### Summarizer Agent 

agent takes the generated timeline and creates a summary of your activity.

## Usage:

Run monitor.py which will create timeline.json and screenshots directory.
Run summarizer.py on it, which will create a summary of your activity. 

make sure you have ANTHROPIC_API_KEY in environment (pydantic agent will use it for summarizing)

## TODOs

1. **Timeline Condensing**: Detect typing sequences and condense them into a single 'typed_text' event rather than logging each keystroke separately
   
2. **Screenshot Element Extraction**: Crop areas around the mouse position to capture the most important UI element (button, tab, text field, etc.)

3. **OCR Support**: Add optical character recognition capabilities for extracting text from captured screenshots

This tool requires macOS accessibility permissions to function properly:

### Permission setup 

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
