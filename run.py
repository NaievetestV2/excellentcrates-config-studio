#!/usr/bin/env python3
"""Launcher for PyInstaller builds: ``pyinstaller ecstudio.spec``."""

from ecstudio.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
