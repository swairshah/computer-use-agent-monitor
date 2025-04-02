#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Setup script for shell completion for osmonitor command.
Run this after installing the package to enable tab completion.
"""

import os
import sys
import argparse
import subprocess

def setup_completion():
    """Set up shell completion for osmonitor command."""
    parser = argparse.ArgumentParser(
        description="Setup shell completion for osmonitor command"
    )
    
    parser.add_argument(
        "--shell",
        choices=["bash", "zsh", "fish", "tcsh"],
        default=None,
        help="Shell to setup completion for (default: auto-detect)"
    )
    
    parser.add_argument(
        "--no-modify-rc",
        action="store_true",
        help="Don't modify shell rc file, just print the commands"
    )
    
    args = parser.parse_args()
    
    # Check if argcomplete is installed
    try:
        import argcomplete
    except ImportError:
        print("Error: argcomplete is not installed.")
        print("Please install it with: pip install argcomplete")
        return 1
    
    # Detect shell if not provided
    shell = args.shell
    if not shell:
        shell = os.path.basename(os.environ.get("SHELL", ""))
    
    if not shell:
        print("Error: Could not detect shell. Please specify with --shell option.")
        return 1
    
    if shell not in ["bash", "zsh", "fish", "tcsh"]:
        print(f"Error: Unsupported shell {shell}. Please use bash, zsh, fish, or tcsh.")
        return 1
    
    # Get the path to the activate-global-python-argcomplete script
    try:
        activate_script = subprocess.check_output(
            ["which", "activate-global-python-argcomplete"],
            text=True
        ).strip()
    except subprocess.CalledProcessError:
        print("Error: activate-global-python-argcomplete not found.")
        print("Please make sure argcomplete is installed correctly.")
        return 1
    
    # Generate the completion command
    if shell == "bash":
        completion_cmd = 'eval "$(register-python-argcomplete osmonitor)"'
        rc_file = os.path.expanduser("~/.bashrc")
    elif shell == "zsh":
        completion_cmd = 'eval "$(register-python-argcomplete osmonitor)"'
        rc_file = os.path.expanduser("~/.zshrc")
    elif shell == "fish":
        completion_cmd = 'register-python-argcomplete --shell fish osmonitor | .'
        rc_file = os.path.expanduser("~/.config/fish/config.fish")
    elif shell == "tcsh":
        completion_cmd = 'eval `register-python-argcomplete --shell tcsh osmonitor`'
        rc_file = os.path.expanduser("~/.tcshrc")
    
    print(f"Shell completion command for {shell}:")
    print(f"  {completion_cmd}")
    
    if not args.no_modify_rc:
        try:
            # Check if the command already exists in the rc file
            with open(rc_file, "r") as f:
                if completion_cmd in f.read():
                    print(f"\nCompletion already set up in {rc_file}.")
                    return 0
            
            # Append the command to the rc file
            with open(rc_file, "a") as f:
                f.write(f"\n# Added by osmonitor setup_completion.py\n{completion_cmd}\n")
            
            print(f"\nAdded completion to {rc_file}")
            print(f"Please restart your shell or run: source {rc_file}")
        except Exception as e:
            print(f"\nError adding completion to {rc_file}: {e}")
            print(f"Please manually add the following line to your {shell} configuration:")
            print(f"  {completion_cmd}")
            return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(setup_completion())