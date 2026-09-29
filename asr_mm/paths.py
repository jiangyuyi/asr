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
import shutil
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
    """Directory holding the llama-funasr-* executables.

    Safe to point at a non-ASCII path: Windows launches the process through
    CreateProcessW before the binary ever sees argv, so the Japanese-Chinese
    characters survive. Only GGUF *model* files need the staging dance below.
    """
    bundled = resource_root() / "runtime"
    if (bundled / _exe_marker()).exists() or any(bundled.glob("llama-funasr-*")):
        return bundled
    return home_root() / "runtime"


def ascii_safe(path: str | os.PathLike) -> bool:
    """True when every character in ``path`` is plain ASCII.

    The GGUF loader in the llama.cpp runtime opens files with narrow ``fopen``,
    so the bytes it receives from argv are interpreted in the system ANSI code
    page. On a Japanese Windows (CP932) a path like ``C:\\Users\\日本語\\...``
    reaches it corrupted and it reports "No such file or directory".
    """
    return all(ord(c) < 128 for c in str(path))


def _writable_ascii_root() -> Path | None:
    """First ASCII-only directory we can actually write to.

    Candidates that share a volume with :func:`home_root` come first, because
    staging then costs a hard link instead of a full copy of ~950 MB of weights.
    Writability is probed rather than assumed: ``C:\\Users\\Public`` is ASCII and
    world-writable on a localized Windows, so a Japanese display name in the
    user's profile never reaches the path the GGUF loader sees.
    """
    if platform.system() != "Windows":
        return None

    def volume(p: Path) -> str:
        drive = p.drive or os.path.splitdrive(str(p))[0]
        return drive.lower()

    home_vol = volume(home_root())
    candidates: list[tuple[bool, Path]] = []   # (same_volume, path)

    public = os.environ.get("PUBLIC")
    if public:
        candidates.append((volume(Path(public)) == home_vol,
                           Path(public) / APP_NAME))
    program_data = os.environ.get("ProgramData") or r"C:\ProgramData"
    candidates.append((volume(Path(program_data)) == home_vol,
                       Path(program_data) / APP_NAME))
    # A same-volume fallback keeps hard links possible when the profile lives
    # on a secondary drive.
    if home_vol:
        candidates.append((True, Path(home_vol + "\\") / APP_NAME))
    sys_drive = (os.environ.get("SystemDrive") or "C:") + "\\"
    candidates.append((volume(Path(sys_drive + "x")) == home_vol,
                       Path(sys_drive) / APP_NAME))

    # Stable sort: same-volume first, original order otherwise.
    candidates.sort(key=lambda item: not item[0])
    for _same_vol, cand in candidates:
        if not ascii_safe(cand):
            continue
        try:
            cand.mkdir(parents=True, exist_ok=True)
            probe = cand / ".write-probe"
            probe.write_text("ok", encoding="ascii")
            probe.unlink()
            return cand
        except OSError:
            continue
    return None


def _stage_models(source: Path, dest: Path) -> None:
    """Mirror model files into ``dest`` using hard links (no extra disk).

    A copy is the fallback when the two directories live on different volumes.
    """
    dest.mkdir(parents=True, exist_ok=True)
    for item in source.glob("*.gguf"):
        target = dest / item.name
        if target.exists() and target.stat().st_size == item.stat().st_size:
            continue
        target.unlink(missing_ok=True)
        try:
            os.link(item, target)
        except OSError:
            shutil.copy2(item, target)


def models_dir() -> Path:
    """Where GGUF models live.

    Normally ``<home>/models``. When that path contains non-ASCII characters on
    Windows, the models are hard-linked into an ASCII directory instead and that
    is what gets returned, so the engine can actually open them.
    """
    home = home_root() / "models"
    if ascii_safe(home):
        home.mkdir(parents=True, exist_ok=True)
        return home
    staging = _writable_ascii_root()
    if staging is None:
        # Nothing ASCII is writable; try the home anyway and let the engine
        # report the failure rather than silently writing models nowhere.
        home.mkdir(parents=True, exist_ok=True)
        return home
    staged = staging / "models"
    if home.exists():
        _stage_models(home, staged)
    else:
        staged.mkdir(parents=True, exist_ok=True)
    return staged


def models_staged() -> bool:
    """True when the GGUF files are being served from an ASCII staging dir."""
    return models_dir() != home_root() / "models"


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
    home = home_root() / "models"
    models = models_dir()
    staged = models != home
    return {
        "platform": f"{platform.system()} {platform.machine()}",
        "python": sys.version.split()[0],
        "frozen": str(is_frozen()),
        "resource_root": str(resource_root()),
        "home_root": str(home_root()),
        "runtime_dir": str(runtime_dir()),
        "models_dir": str(models) + ("  (ASCII 暂存)" if staged else ""),
        "ffmpeg": str(ffmpeg_exe() or "(ffmpeg not found on PATH)"),
    }
