"""Verify each macOS archive carries a launcher that actually points at the
binary inside that archive — with usable zip permission bits.

Regression guard for a real bug: the console archive shipped a launcher that
exec'd ``asr-mm-gui``, which is not in that zip.
"""
from __future__ import annotations

import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(r"D:\Work\asr_mm")
LABEL = sys.argv[1] if len(sys.argv) > 1 else "macos-arm64"
VERSION = sys.argv[2] if len(sys.argv) > 2 else "dev"
OUT = ROOT / "tools" / "archive_check.txt"

lines: list[str] = []
fails: list[str] = []


def say(m=""):
    lines.append(m)
    OUT.write_text("\n".join(lines), encoding="utf-8")


def check(label, ok, detail=""):
    say(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f"  — {detail}" if detail else ""))
    if not ok:
        fails.append(label)


work = ROOT / "tools" / "_archcheck"
shutil.rmtree(work, ignore_errors=True)
work.mkdir(parents=True)
r = subprocess.run(
    [sys.executable, str(ROOT / "packaging" / "make_archives.py"),
     "--version", VERSION, "--label", LABEL, "--out", str(work)],
    capture_output=True, cwd=str(ROOT))
say(r.stdout.decode("utf-8", "replace").strip())
if r.returncode != 0:
    say(r.stderr.decode("utf-8", "replace")[-600:])
    raise SystemExit(1)
say()

for z in sorted(work.glob("*.zip")):
    bundle = "asr-mm-gui" if "gui" in z.name else "asr-mm"
    say(f"--- {z.name}  (bundle: {bundle}) ---")
    with zipfile.ZipFile(z) as zf:
        names = zf.namelist()
        check(f"{bundle}: launcher present",
              any(n.endswith(".command") for n in names))
        check(f"{bundle}: readme present", "README-macOS.txt" in names)
        check(f"{bundle}: payload is under {bundle}/",
              any(n.startswith(bundle + "/") for n in names))

        launcher = next((n for n in names if n.endswith(".command")), None)
        if launcher:
            info = zf.getinfo(launcher)
            mode = info.external_attr >> 16
            body = zf.read(launcher).decode("utf-8")
            check(f"{bundle}: launcher is executable",
                  bool(mode & stat.S_IXUSR), oct(mode & 0o777))
            check(f"{bundle}: stored as a Unix entry",
                  info.create_system == 3, str(info.create_system))
            check(f"{bundle}: clears the quarantine mark", "xattr -cr" in body)
            want = f'"$DIR/{bundle}/{bundle}"'
            check(f"{bundle}: launches the binary this archive contains",
                  want in body, f"expected {want}")
            other = "asr-mm-gui" if bundle == "asr-mm" else None
            check(f"{bundle}: does not point at the other bundle",
                  not other or f'"$DIR/{other}/{other}"' not in body)

        if "README-macOS.txt" in names:
            readme = zf.read("README-macOS.txt").decode("utf-8")
            check(f"{bundle}: readme is trilingual",
                  all(k in readme for k in ("首次运行", "First run", "初回起動")))
            check(f"{bundle}: readme gives the xattr fallback",
                  "xattr -cr" in readme)
    say()

shutil.rmtree(work, ignore_errors=True)
say(f"RESULT: {len(fails)} failure(s)")
for f in fails:
    say(f"  FAILED: {f}")
print("WROTE", OUT)
