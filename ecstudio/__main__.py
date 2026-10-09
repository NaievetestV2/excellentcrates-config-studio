"""``python -m ecstudio`` launches the desktop app."""

from __future__ import annotations

import sys


def main() -> int:
    try:
        import tkinter  # noqa: F401
    except ImportError:
        sys.stderr.write(
            "Tkinter is not available.\n"
            "Install it first, e.g.\n"
            "  Debian/Ubuntu: sudo apt install python3-tk\n"
            "  Fedora:        sudo dnf install python3-tkinter\n"
            "  Windows/macOS: use the bundled .exe / .app build\n"
        )
        return 1

    from .gui import main as gui_main

    gui_main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
