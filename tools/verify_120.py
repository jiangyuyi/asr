"""Download the 1.2.0 assets and verify them for real, end to end."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(r"D:\Work\asr_mm")
TMP = ROOT / "tools" / "_verify120"
LOG = ROOT / "tools" / "verify_120.txt"
VIDEO = ROOT / "samples/课堂录像示例.mp4"
TAG = "v1.2.0"

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
say("RELEASE 1.2.0 VERIFICATION")
say("=" * 72)
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True, exist_ok=True)

for pattern in (f"asr-mm-{TAG[1:]}-windows-x64.zip",
                f"asr-mm-gui-{TAG[1:]}-windows-x64.zip",
                f"asr-mm-{TAG[1:]}-macos-arm64.zip"):
    r = subprocess.run(["gh", "release", "download", TAG, "-D", str(TMP),
                        "--clobber", "-p", pattern], capture_output=True)
    check(f"download {pattern}", r.returncode == 0,
          f"{(TMP / pattern).stat().st_size / 1_048_576:.0f} MB"
          if (TMP / pattern).exists() else r.stderr.decode()[-120:])

# ------------------------------------------------------------------ macOS
say("\n--- macOS payload ---")
with zipfile.ZipFile(TMP / f"asr-mm-{TAG[1:]}-macos-arm64.zip") as z:
    z.extractall(TMP / "mac")
mac = TMP / "mac" / "asr-mm"
for rel in ("_internal/runtime/llama-funasr-cli", "_internal/ffmpeg/ffmpeg"):
    head = (mac / rel).open("rb").read(4)
    check(f"macOS {Path(rel).name} is Mach-O arm64",
          head in (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe"), head.hex())
check("no stray .exe in macOS bundle", not list(mac.rglob("*.exe")))

# ------------------------------------------------------------------ Windows
say("\n--- Windows console build ---")
with zipfile.ZipFile(TMP / f"asr-mm-{TAG[1:]}-windows-x64.zip") as z:
    z.extractall(TMP / "win")
exe = TMP / "win" / "asr-mm" / "asr-mm.exe"
env = dict(os.environ)
env["ASR_MM_HOME"] = str(ROOT / ".asrhome")
env["PYTHONIOENCODING"] = "utf-8"
env["PYTHONUTF8"] = "1"

r = subprocess.run([str(exe), "--version"], capture_output=True, env=env, timeout=180)
version = r.stdout.decode("utf-8", "replace").strip()
check("reports the new version", "1.2.0" in version, version)

for lang, needle in (("zh", "默认模型"), ("en", "Default model"),
                     ("ja", "既定のモデル")):
    r = subprocess.run([str(exe), "--lang", lang, "models", "list"],
                       capture_output=True, env=env, timeout=300)
    check(f"--lang {lang} still works", r.returncode == 0
          and needle in r.stdout.decode("utf-8", "replace"))

# a Japanese-named file, transcribed by the frozen build
jp = TMP / "日本語の動画"
jp.mkdir(exist_ok=True)
shutil.copy2(VIDEO, jp / "テスト動画.avi")
r = subprocess.run(
    [str(exe), "--lang", "ja", "transcribe", str(jp / "テスト動画.avi"),
     "-s", "00:00:15", "-e", "00:00:30", "--stdout", "--output-format", "srt",
     "--no-summary"], capture_output=True, env=env, timeout=900)
srt = r.stdout.decode("utf-8", "replace")
check("transcribes a Japanese-named file", r.returncode == 0 and "-->" in srt,
      srt.strip().splitlines()[2][:50] if "-->" in srt
      else r.stderr.decode("utf-8", "replace")[-160:])

# ------------------------------------------------------------------ GUI
say("\n--- Windows GUI build (exercises the new loader) ---")
with zipfile.ZipFile(TMP / f"asr-mm-gui-{TAG[1:]}-windows-x64.zip") as z:
    z.extractall(TMP / "wingui")
gui = TMP / "wingui" / "asr-mm-gui" / "asr-mm-gui.exe"
check("GUI bundle has a complete _internal",
      (gui.parent / "_internal" / "python311.dll").exists()
      and (gui.parent / "_internal" / "ffmpeg" / "ffmpeg.exe").exists())

p = subprocess.Popen([str(gui), str(VIDEO)], env=env)
alive = 0
for _ in range(18):
    time.sleep(1)
    if p.poll() is not None:
        break
    alive += 1
check("GUI launches and stays up (loader thread works)", p.poll() is None,
      f"{alive}s alive, rc={p.returncode}" if p.poll() is not None else f"{alive}s")
if p.poll() is None:
    p.terminate()
    try:
        p.wait(timeout=6)
    except subprocess.TimeoutExpired:
        p.kill()

say("")
say("=" * 72)
say(f"RESULT: {len(fails)} failure(s)")
for f in fails:
    say(f"  FAILED: {f}")
say("=" * 72)
shutil.rmtree(TMP, ignore_errors=True)
print("WROTE", LOG)
