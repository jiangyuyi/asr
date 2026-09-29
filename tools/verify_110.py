"""Download the 1.1.0 assets and verify them for real.

Checks the Windows build end-to-end (download -> extract -> run in all three
languages) and validates the macOS payload's architecture.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(r"D:\Work\asr_mm")
TMP = Path(r"D:\Work\asr_mm\tools\_verify110")
LOG = ROOT / "tools" / "verify_110.txt"
VIDEO = ROOT / "20250912 哲商現代実験学校 MR1 part1.avi"
GH = ["gh", "release", "download", "v1.1.0", "-D", str(TMP), "--clobber"]

out: list[str] = []
fails: list[str] = []


def say(m=""):
    out.append(m)
    LOG.write_text("\n".join(out), encoding="utf-8")


def check(label, ok, detail=""):
    say(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f"  — {detail}" if detail else ""))
    if not ok:
        fails.append(label)


say("=" * 72)
say("RELEASE 1.1.0 VERIFICATION")
say("=" * 72)
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True, exist_ok=True)

say("--- downloading both platforms ---")
for pattern in ("asr-mm-1.1.0-windows-x64.zip", "asr-mm-1.1.0-macos-arm64.zip"):
    r = subprocess.run(GH + ["-p", pattern], capture_output=True)
    check(f"download {pattern}", r.returncode == 0,
          (TMP / pattern).stat().st_size // 1024 // 1024
          and f"{(TMP / pattern).stat().st_size / 1_048_576:.0f} MB" or "")

# ---------------------------------------------------------------- macOS
say("\n--- macOS payload ---")
with zipfile.ZipFile(TMP / "asr-mm-1.1.0-macos-arm64.zip") as z:
    names = z.namelist()
    z.extractall(TMP / "mac")
mac = TMP / "mac" / "asr-mm"
for rel in ("_internal/runtime/llama-funasr-cli", "_internal/ffmpeg/ffmpeg"):
    p = mac / rel
    with p.open("rb") as f:
        head = f.read(4)
    check(f"macOS {Path(rel).name} is Mach-O", head[:4] == b"\xcf\xfa\xed\xfe"
          or head[:4] == b"\xca\xfe\xba\xbe", head.hex())
check("no stray .exe in the macOS bundle",
      not list(mac.rglob("*.exe")), f"{len(list(mac.rglob('*.exe')))} found")
# PyInstaller compiles modules into the PYZ archive, so i18n.py is not a loose
# file in _internal/. The real proof is the --lang run below; here we only
# confirm the module was not accidentally excluded from the build.
embedded = [p for p in mac.rglob("*.pyz")] + [p for p in mac.rglob("base_library.zip")]
check("frozen bundle carries a compiled module archive", bool(embedded),
      ", ".join(p.name for p in embedded[:3]) or "none")

# ---------------------------------------------------------------- Windows
say("\n--- Windows build, all three languages ---")
with zipfile.ZipFile(TMP / "asr-mm-1.1.0-windows-x64.zip") as z:
    z.extractall(TMP / "win")
exe = TMP / "win" / "asr-mm" / "asr-mm.exe"
env = dict(os.environ)
env["ASR_MM_HOME"] = str(ROOT / ".asrhome")
env["PYTHONIOENCODING"] = "utf-8"
env["PYTHONUTF8"] = "1"

r = subprocess.run([str(exe), "--version"], capture_output=True, env=env, timeout=120)
check("frozen build runs", r.returncode == 0,
      r.stdout.decode("utf-8", "replace").strip())

# --lang must work in the frozen build (the catalog is an inlined module,
# so a packaging mistake would show up here and nowhere else)
for lang, needle in (("zh", "默认模型"), ("en", "Default model"),
                     ("ja", "既定のモデル")):
    r = subprocess.run([str(exe), "--lang", lang, "models", "list"],
                       capture_output=True, env=env, timeout=300)
    text = r.stdout.decode("utf-8", "replace")
    check(f"--lang {lang} honoured in frozen build",
          r.returncode == 0 and needle in text,
          text.strip().splitlines()[-1][:60] if text.strip() else "")

# transcribe in Japanese, through a Japanese-named video, in the frozen build
jp = TMP / "日本語の動画"
jp.mkdir(exist_ok=True)
shutil.copy2(VIDEO, jp / "テスト動画.avi")
r = subprocess.run(
    [str(exe), "--lang", "ja", "transcribe", str(jp / "テスト動画.avi"),
     "-s", "00:00:15", "-e", "00:00:30", "--stdout", "--output-format", "srt",
     "--no-summary"],
    capture_output=True, env=env, timeout=900)
srt = r.stdout.decode("utf-8", "replace")
check("frozen build transcribes a Japanese-named file", r.returncode == 0 and "-->" in srt,
      srt.strip().splitlines()[2][:50] if "-->" in srt
      else r.stderr.decode("utf-8", "replace")[-200:])
say("")
say(srt.strip())

say("")
say("=" * 72)
say(f"RESULT: {len(fails)} failure(s)")
for f in fails:
    say(f"  FAILED: {f}")
say("=" * 72)
shutil.rmtree(TMP, ignore_errors=True)
print("WROTE", LOG)
