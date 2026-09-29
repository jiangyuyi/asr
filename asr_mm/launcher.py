"""Console entry point: `asr-mm <command>` (also `asr-mm gui` for the window).

Uses absolute imports on purpose: PyInstaller executes this file as a top-level
``__main__`` script with no package context, so relative imports would fail in
the frozen build while working fine under ``python -m``.
"""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("gui", "--gui"):
        try:
            from asr_mm.gui.app import main as gui_main
        except ImportError:
            print("GUI 依赖未安装。请运行: pip install PySide6", file=sys.stderr)
            return 1
        return gui_main()
    from asr_mm.cli import main as cli_main
    return cli_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
