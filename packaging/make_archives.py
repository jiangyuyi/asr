"""Create the release archives.

Uses Python's zipfile rather than a `zip` binary: Git Bash on Windows ships
without `zip`, and relying on it made the Windows job fail for a reason that has
nothing to do with the build.

    python packaging/make_archives.py --version 1.0.0 --label windows-x64
"""
from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
BUNDLES = ("asr-mm", "asr-mm-gui")


def archive(bundle: str, out_dir: Path, version: str, label: str) -> Path:
    src = DIST / bundle
    if not src.is_dir():
        raise SystemExit(f"缺少构建产物: {src}\n请先运行 pyinstaller。")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{bundle}-{version}-{label}.zip"
    print(f"packing {bundle} -> {out.name} …", flush=True)
    files = [p for p in src.rglob("*") if p.is_file()]
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in files:
            z.write(p, Path(bundle) / p.relative_to(src))
    print(f"  {len(files)} files, {out.stat().st_size / 1_048_576:.1f} MB")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="dev")
    ap.add_argument("--label", required=True, help="e.g. windows-x64 / macos-arm64")
    ap.add_argument("--out", default=str(ROOT / "release"))
    args = ap.parse_args()

    out_dir = Path(args.out)
    made = [archive(b, out_dir, args.version, args.label) for b in BUNDLES]
    total = sum(p.stat().st_size for p in made)
    print(f"\ntotal {total / 1_048_576:.1f} MB in {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
