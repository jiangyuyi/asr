"""Launch the built GUI from ``dist/`` — the only place it can actually run.

Convenience wrapper so nobody has to remember that the exes PyInstaller leaves
in its work directory are not runnable: ``_internal/`` (python311.dll, ffmpeg,
the ASR engine) is only assembled during the COLLECT step, into ``dist/``.

    python tools/run_gui.py [video.mp4]
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUI = ROOT / "dist" / "asr-mm-gui" / "asr-mm-gui.exe"
CLI = ROOT / "dist" / "asr-mm" / "asr-mm.exe"
INTERNAL_DLL = "python311.dll"


def dist_dir() -> Path:
    return GUI.parent


def _utf8_console() -> None:
    """Force UTF-8 on stdout/stderr.

    A Windows console using CP936 would otherwise render this script's Chinese
    error message as mojibake — the same trap the ASR engine's output sets.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def explain(problem: str) -> None:
    print(f"无法启动图形界面：{problem}\n", file=sys.stderr)
    print("  可运行程序在 dist/ 目录：", file=sys.stderr)
    print(f"    {GUI if GUI.exists() else CLI}", file=sys.stderr)
    print("\n  缺少 _internal/ 说明构建没走完 COLLECT 阶段，请重新构建：", file=sys.stderr)
    print("    python packaging/prepare_payload.py --target win", file=sys.stderr)
    print("    python -m PyInstaller packaging/asr-mm.spec --noconfirm"
          " --workpath .pyinstaller-cache", file=sys.stderr)
    sys.exit(1)


def main() -> int:
    _utf8_console()
    if not GUI.exists():
        explain(f"找不到 {GUI}")
    if not (dist_dir() / "_internal" / INTERNAL_DLL).exists():
        explain(f"{dist_dir() / '_internal'} 不完整，缺少 {INTERNAL_DLL}")

    cmd = [str(GUI)] + sys.argv[1:]
    print("启动:", " ".join(cmd))
    return subprocess.run(cmd).returncode


if __name__ == "__main__":
    raise SystemExit(main())
