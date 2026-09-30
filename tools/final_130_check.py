"""Verify the published 1.3.0 assets, especially the CA bundle in the macOS one."""
from __future__ import annotations

import shutil
import stat
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(r"D:\Work\asr_mm")
TMP = ROOT / "tools" / "_final130"
OUT = ROOT / "tools" / "final_130.txt"
TAG = "v1.3.0"

lines: list[str] = []
fails: list[str] = []


def say(m=""):
    lines.append(m)
    OUT.write_text("\n".join(lines), encoding="utf-8")


def check(label, ok, detail=""):
    say(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f"  — {detail}" if detail else ""))
    if not ok:
        fails.append(label)


shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True)
say("=" * 72)
say("RELEASE 1.3.0 VERIFICATION")
say("=" * 72)

for name in (f"asr-mm-gui-{TAG[1:]}-macos-arm64.zip",
             f"asr-mm-{TAG[1:]}-macos-arm64.zip",
             f"asr-mm-{TAG[1:]}-windows-x64.zip"):
    r = subprocess.run(["gh", "release", "download", TAG, "-D", str(TMP),
                        "--clobber", "-p", name], capture_output=True)
    z = TMP / name
    check(f"download {name}", r.returncode == 0 and z.exists(),
          f"{z.stat().st_size / 1_048_576:.0f} MB" if z.exists()
          else r.stderr.decode()[-120:])
    if not z.exists():
        continue
    say(f"  packed {z.stat().st_size / 1_048_576:.0f} MB")

# --- the fix itself: CA bundle + truststore must be inside the bundle ----
say()
say("--- macOS GUI: CA bundle present ---")
gui_zip = TMP / f"asr-mm-gui-{TAG[1:]}-macos-arm64.zip"
with zipfile.ZipFile(gui_zip) as zf:
    names = zf.namelist()
    cacerts = [n for n in names if n.endswith("cacert.pem")]
    check("certifi cacert.pem shipped", bool(cacerts),
          cacerts[0] if cacerts else "not found")
    if cacerts:
        info = zf.getinfo(cacerts[0])
        check("cacert.pem is substantial", info.file_size > 100_000,
              f"{info.file_size:,} bytes")
        body = zf.read(cacerts[0]).decode("utf-8", "replace")
        check("cacert.pem holds real certificates",
              body.count("BEGIN CERTIFICATE") > 50,
              f"{body.count('BEGIN CERTIFICATE')} certs")
    launcher = next((n for n in names if n.endswith(".command")), None)
    check("launcher still shipped", launcher is not None, launcher or "")
    if launcher:
        mode = zf.getinfo(launcher).external_attr >> 16
        check("launcher still executable", bool(mode & stat.S_IXUSR),
              oct(mode & 0o777))
    check("engine binaries still present",
          any("_internal/runtime/llama-funasr" in n for n in names))
    check("no stray .exe", not any(n.endswith(".exe") for n in names))

# --- run the Windows console build ---------------------------------------
say()
say("--- Windows console build ---")
with zipfile.ZipFile(TMP / f"asr-mm-{TAG[1:]}-windows-x64.zip") as zf:
    zf.extractall(TMP / "win")
exe = TMP / "win" / "asr-mm" / "asr-mm.exe"

import os  # noqa: E402
env = dict(os.environ)
env["ASR_MM_HOME"] = str(ROOT / ".asrhome")
env["PYTHONIOENCODING"] = "utf-8"
env["PYTHONUTF8"] = "1"

v = subprocess.run([str(exe), "--version"], capture_output=True, env=env,
                   timeout=180).stdout.decode("utf-8", "replace")
check("version", "1.3.0" in v, v.strip())

r = subprocess.run([str(exe), "net-check"], capture_output=True, env=env,
                   timeout=300)
out = r.stdout.decode("utf-8", "replace")
say("")
say("--- asr-mm net-check (frozen, published build) ---")
say(out.strip())
say("")
check("net-check exits 0 from the published build", r.returncode == 0,
      f"exit {r.returncode}")
check("uses the OS trust store", "系统信任库" in out)
check("reports certificate issuers", "签发者" in out)
check("all sources reachable", out.count("[OK") == 3, f"{out.count('[OK')}")

r = subprocess.run([str(exe), "--lang", "ja", "transcribe",
                    str(ROOT / "课堂录像示例.mp4"),
                    "-s", "00:00:15", "-e", "00:00:30", "--stdout",
                    "--output-format", "srt", "--no-summary"],
                   capture_output=True, env=env, timeout=900)
srt = r.stdout.decode("utf-8", "replace")
check("still transcribes correctly", r.returncode == 0 and "-->" in srt,
      srt.strip().splitlines()[2][:44] if "-->" in srt else "")

shutil.rmtree(TMP, ignore_errors=True)
say("")
say(f"RESULT: {len(fails)} failure(s)")
for f in fails:
    say(f"  FAILED: {f}")
print("WROTE", OUT)
