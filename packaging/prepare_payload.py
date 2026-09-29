"""Stage the read-only payload that ships inside the bundle.

Runs before PyInstaller so the spec can treat these as plain data files:

* ``runtime/llama-funasr-*``  — the CPU ASR engine (~5 MB, no Python needed)
* ``ffmpeg/ffmpeg``            — the static decoder (~40 MB)

Models deliberately do *not* go here; they are downloaded on first use into the
user-writable home root, which keeps the installer small and lets macOS ship a
read-only bundle.

Usage:  python packaging/prepare_payload.py [--target win|mac|linux]
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from asr_mm import catalog, downloader  # noqa: E402

PAYLOAD = ROOT / "packaging" / "payload"

TARGET_RUNTIME = {
    "win": "windows-x64-avx2",
    "win-compat": "windows-x64",
    "mac": "macos-arm64",
    "linux": "linux-x64",
}


def stage_runtime(target: str) -> Path:
    key = TARGET_RUNTIME[target]
    spec = catalog.RUNTIMES[key]
    dest = PAYLOAD / "runtime"
    dest.mkdir(parents=True, exist_ok=True)

    archive = ROOT / "packaging" / "cache" / spec.archive
    archive.parent.mkdir(parents=True, exist_ok=True)
    if not archive.exists():
        print(f"downloading {spec.label} …", flush=True)
        downloader.download(spec.url, archive, expect_sha256=spec.sha256,
                            progress=downloader.progress_printer("  "))
    print(f"extracting {spec.label} …", flush=True)
    tmp = PAYLOAD / "_rt"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)
    downloader._extract(archive, tmp)
    for member in spec.members:
        src = next(tmp.rglob(member), None)
        if src is None:
            raise SystemExit(f"归档中找不到 {member}")
        shutil.copy2(src, dest / member)
        # Ship the download helper too, so a user can fetch extra models later.
        for extra in ("download-funasr-model.sh", "README.md"):
            s = next(tmp.rglob(extra), None)
            if s is not None:
                shutil.copy2(s, dest / extra)
                break
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"  runtime -> {dest}")
    return dest


def stage_ffmpeg() -> Path:
    import imageio_ffmpeg
    dest = PAYLOAD / "ffmpeg"
    dest.mkdir(parents=True, exist_ok=True)
    name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    src = Path(imageio_ffmpeg.get_ffmpeg_exe())
    shutil.copy2(src, dest / name)
    (dest / name).chmod(0o755)
    print(f"  ffmpeg -> {dest / name}  "
          f"({src.stat().st_size / 1_048_576:.0f} MB)")
    return dest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="win",
                    choices=list(TARGET_RUNTIME), help="platform whose runtime to embed")
    ap.add_argument("--skip-ffmpeg", action="store_true")
    args = ap.parse_args()

    print(f"payload -> {PAYLOAD}")
    stage_runtime(args.target)
    if not args.skip_ffmpeg:
        stage_ffmpeg()
    total = sum(p.stat().st_size for p in PAYLOAD.rglob("*") if p.is_file())
    print(f"\ntotal payload: {total / 1_048_576:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
