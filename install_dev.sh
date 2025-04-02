#!/bin/bash
# Installation script for development mode

# Make sure the script is run from the correct directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Check if python3 is available
command -v python3 >/dev/null 2>&1 || { 
    echo >&2 "Error: python3 is required but not installed. Aborting."; 
    exit 1; 
}

# Check if a virtual environment already exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    if [ $? -ne 0 ]; then
        echo "Failed to create virtual environment. Please check your Python installation."
        exit 1
    fi
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate
if [ $? -ne 0 ]; then
    echo "Failed to activate virtual environment."
    exit 1
fi

# Install requirements
echo "Installing requirements..."
pip install -r requirements.txt
if [ $? -ne 0 ]; then
    echo "Failed to install requirements."
    exit 1
fi

# Install the package in development mode
echo "Installing the package in development mode..."
pip install -e .
if [ $? -ne 0 ]; then
    echo "Failed to install the package in development mode."
    exit 1
fi

# Make setup_completion.py executable
chmod +x setup_completion.py

# Show success message
echo ""
echo "Installation completed successfully!"
echo ""
echo "To start using osmonitor:"
echo "1. Activate the virtual environment: source venv/bin/activate"
echo "2. Set up shell completion (optional): python setup_completion.py"
echo "3. Run the command: osmonitor"
echo ""
echo "See README_OSMONITOR.md for more details."