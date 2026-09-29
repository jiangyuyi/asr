"""Filesystem layout.

Two distinct roots:

* **resource root** — read-only files that ship with the app (ffmpeg binary, the
  llama.cpp runtime). Lives inside the PyInstaller bundle when frozen.
* **home root** — user-writable state (downloaded GGUF models, settings,
  output defaults). Never inside the bundle, which is read-only on macOS.

``ASR_MM_HOME`` overrides the home root, which is what the tests use.
"""
from __future__ import annotations

import os
import platform
import sys
from pathlib import Path

APP_NAME = "asr-mm"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    """Read-only directory holding bundled binaries."""
    override = os.environ.get("ASR_MM_RESOURCE_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def home_root() -> Path:
    """User-writable directory holding downloaded models and settings."""
    override = os.environ.get("ASR_MM_HOME")
    if override:
        root = Path(override).expanduser()
    elif platform.system() == "Windows":
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
        root = Path(base) / APP_NAME
    elif platform.system() == "Darwin":
        root = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
        root = Path(base) / APP_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def runtime_dir() -> Path:
    """Directory holding the llama-funasr-* executables."""
    bundled = resource_root() / "runtime"
    if (bundled / _exe_marker()).exists() or any(bundled.glob("llama-funasr-*")):
        return bundled
    return home_root() / "runtime"


def models_dir() -> Path:
    d = home_root() / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_dir() -> Path:
    d = home_root() / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def settings_path() -> Path:
    return home_root() / "settings.json"


def ffmpeg_exe() -> Path | None:
    """Bundled static ffmpeg, if present."""
    name = "ffmpeg.exe" if platform.system() == "Windows" else "ffmpeg"
    p = resource_root() / "ffmpeg" / name
    return p if p.exists() else None


def _exe_marker() -> str:
    return "llama-funasr-cli.exe" if platform.system() == "Windows" else "llama-funasr-cli"


def binary_suffix() -> str:
    return ".exe" if platform.system() == "Windows" else ""


def describe_layout() -> dict[str, str]:
    return {
        "platform": f"{platform.system()} {platform.machine()}",
        "python": sys.version.split()[0],
        "frozen": str(is_frozen()),
        "resource_root": str(resource_root()),
        "home_root": str(home_root()),
        "runtime_dir": str(runtime_dir()),
        "models_dir": str(models_dir()),
        "ffmpeg": str(ffmpeg_exe() or "(使用 PATH 中的 ffmpeg)"),
    }
