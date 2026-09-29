"""Create the release archives.

Uses Python's zipfile rather than a `zip` binary: Git Bash on Windows ships
without `zip`, and relying on it made the Windows job fail for a reason that has
nothing to do with the build. The same reasoning applies to the step body in CI —
it is plain Python, so it runs identically under PowerShell and bash.

    python packaging/make_archives.py --label windows-x64
    GITHUB_REF_NAME=v1.0.0 python packaging/make_archives.py --label macos-arm64
"""
from __future__ import annotations

import argparse
import os
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import macos_extras  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
BUNDLES = ("asr-mm", "asr-mm-gui")


def default_version() -> str:
    """v1.0.0 -> 1.0.0, taken from the tag on CI."""
    ref = os.environ.get("GITHUB_REF_NAME", "").strip()
    if not ref or not ref.startswith("v"):
        return "dev"
    return ref[1:]


def archive(bundle: str, out_dir: Path, version: str, label: str) -> Path:
    src = DIST / bundle
    if not src.is_dir():
        raise SystemExit(f"缺少构建产物: {src}\n请先运行 pyinstaller。")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{bundle}-{version}-{label}.zip"
    is_macos = label.startswith("macos")
    print(f"packing {bundle} -> {out.name} …", flush=True)

    files = [p for p in src.rglob("*") if p.is_file()]
    raw = sum(p.stat().st_size for p in files)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in files:
            # Executable bits are not stored by zipfile's own write(); carry
            # them over explicitly or the binaries lose +x on extraction.
            info = zipfile.ZipInfo.from_file(p, str(Path(bundle) / p.relative_to(src)))
            mode = p.stat().st_mode
            info.external_attr = ((mode & 0o7777) | 0o100000) << 16
            if is_macos:
                info.create_system = 3        # Unix, so the mode above applies
            # writestr() reads compress_type off the ZipInfo, and that defaults
            # to ZIP_STORED — it does not inherit the archive's setting. Without
            # this the bundle ships uncompressed (115 MB -> 308 MB).
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, p.read_bytes())

        if is_macos:
            # A quarantined, unsigned bundle will not load its own libraries.
            # Ship a launcher that clears the mark on first run, pointing at
            # the binary this archive actually contains.
            extras = macos_extras.files_for(bundle)
            for name, body in extras.items():
                extra = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
                executable = name.endswith(".command")
                extra.create_system = 3        # Unix, so the mode below applies
                extra.external_attr = (0o100755 if executable else 0o100644) << 16
                extra.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(extra, body.encode("utf-8"))
            print(f"  + {len(extras)} macOS helper files "
                  f"({', '.join(extras)})")

    size_mb = out.stat().st_size / 1_048_576
    ratio = out.stat().st_size / raw if raw else 1.0
    print(f"  {len(files)} files, {raw / 1_048_576:.0f} MB raw -> "
          f"{size_mb:.1f} MB packed ({ratio:.0%})")
    # A bundle that barely compresses means deflate silently stopped applying.
    if size_mb > raw / 1_048_576 * 0.75:
        raise SystemExit(
            f"压缩似乎未生效：{raw / 1_048_576:.0f} MB 原始内容只压到 "
            f"{size_mb:.1f} MB。检查 writestr() 是否设置了 compress_type。")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default=None,
                    help="defaults to $GITHUB_REF_NAME without the leading v")
    ap.add_argument("--label", required=True, help="e.g. windows-x64 / macos-arm64")
    ap.add_argument("--out", default=str(ROOT / "release"))
    args = ap.parse_args()

    version = args.version or default_version()
    out_dir = Path(args.out)
    print(f"version={version}  label={args.label}")
    made = [archive(b, out_dir, version, args.label) for b in BUNDLES]
    total = sum(p.stat().st_size for p in made)
    print(f"\ntotal {total / 1_048_576:.1f} MB in {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
