"""Windowed entry point: double-clickable GUI with no console window.

Absolute imports for the same reason as ``launcher.py`` — PyInstaller runs this
as a top-level script.
"""
from __future__ import annotations

import sys


def main() -> int:
    from asr_mm.gui.app import main as gui_main
    return gui_main()


if __name__ == "__main__":
    raise SystemExit(main())
