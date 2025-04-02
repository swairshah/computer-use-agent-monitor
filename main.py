#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Main entry point for the macOS UI Monitor.
This is just a convenience wrapper to run the CLI.
"""

import sys
from osmonitor.cli import main

if __name__ == "__main__":
    sys.exit(main())