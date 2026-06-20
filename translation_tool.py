#!/usr/bin/env python3
"""Compatibility entry point. The app now lives in the split_translator package.

Run with either:
    python translation_tool.py
    python -m split_translator
"""

import sys

from split_translator.app import main

if __name__ == "__main__":
    sys.exit(main())
