"""Verify the model-path fix: a non-ASCII home must not break GGUF loading."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"D:\Work\asr_mm")
WORK = ROOT / "tools" / "enc_fix"
LOG = ROOT / "tools" / "enc_fix.txt"
sys.path.insert(0, str(ROOT))

out: list[str] = []
fails: list[str] = []


def say(m: str = "") -> None:
    out.append(m)
    LOG.write_text("\n".join(out), encoding="utf-8")


def check(label: str, ok: bool, detail: str = "") -> None:
    say(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f"  — {detail}" if detail else ""))
    if not ok:
        fails.append(label)


# Start from a clean staging dir, otherwise a previous run's *copy* of the
# models is already sitting there with a matching size and the hard-link
# branch never runs.
STAGING = Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "asr-mm"
shutil.rmtree(STAGING, ignore_errors=True)

# Build a home directory whose every component is non-ASCII, like a Japanese
# Windows profile: C:\Users\日本語\AppData\Local\asr-mm
shutil.rmtree(WORK, ignore_errors=True)
JP_HOME = WORK / "日本語ユーザー" / "AppData" / "Local" / "asr-mm"
(JP_HOME / "models").mkdir(parents=True, exist_ok=True)
(JP_HOME / "runtime").mkdir(parents=True, exist_ok=True)

src_models = ROOT / ".asrhome" / "models"
src_runtime = ROOT / ".asrhome" / "runtime"
for f in src_models.glob("*.gguf"):
    shutil.copy2(f, JP_HOME / "models" / f.name)
# runtime_status() requires all four engine binaries to be present
for e in ("llama-funasr-cli.exe", "llama-funasr-paraformer.exe",
          "llama-funasr-sensevoice.exe", "llama-funasr-vad.exe"):
    shutil.copy2(src_runtime / e, JP_HOME / "runtime" / e)

VIDEO = ROOT / "samples/课堂录像示例.mp4"
env = dict(os.environ)
env["ASR_MM_HOME"] = str(JP_HOME)
env["PYTHONIOENCODING"] = "utf-8"
env["PYTHONUTF8"] = "1"

say("=" * 72)
say("MODEL PATH FIX — non-ASCII home")
say("=" * 72)
say(f"ASR_MM_HOME = {JP_HOME}")
say("")

probe = r"""
import json, sys
sys.path.insert(0, r"{root}")
from asr_mm import paths
print(json.dumps({{
    "home": str(paths.home_root()),
    "models": str(paths.models_dir()),
    "runtime": str(paths.runtime_dir()),
    "ascii_safe_home": paths.ascii_safe(paths.home_root() / "models"),
    "staged": paths.models_staged(),
}}, ensure_ascii=False))
""".format(root=ROOT)

r = subprocess.run([sys.executable, "-c", probe], capture_output=True, env=env)
info = json.loads(r.stdout.decode("utf-8", "replace"))
say(json.dumps(info, ensure_ascii=False, indent=2))
say("")

check("models dir is ASCII-only",
      all(ord(c) < 128 for c in info["models"]),
      info["models"])
check("staging engaged for non-ASCII home", info["staged"] is True)
check("GGUF files present in staged dir",
      len(list(Path(info["models"]).glob("*.gguf"))) == len(list(src_models.glob("*.gguf"))),
      f"{len(list(Path(info['models']).glob('*.gguf')))} gguf")
links = {f.name: os.stat(Path(info["models"]) / f.name).st_nlink
         for f in src_models.glob("*.gguf")}
check("staged via hard links (no extra disk)", all(v >= 2 for v in links.values()),
      ", ".join(f"{k}:{v}" for k, v in list(links.items())[:3]))
say("")

say("--- end-to-end transcribe through the non-ASCII home ---")
cmd = [sys.executable, "-m", "asr_mm", "transcribe", str(VIDEO),
       "-s", "00:00:15", "-e", "00:00:30",
       "-m", "paraformer", "--stdout", "--output-format", "srt", "--no-summary"]
r = subprocess.run(cmd, capture_output=True, env=env, cwd=str(ROOT), timeout=900)
srt = r.stdout.decode("utf-8", "replace")
err = r.stderr.decode("utf-8", "replace")
check("transcribe succeeded", r.returncode == 0 and "-->" in srt,
      err.strip()[-200:] if r.returncode != 0 else srt.strip().splitlines()[2][:60])
say("")
say(srt.strip())
say("")
say("=" * 72)
say(f"RESULT: {len(fails)} failure(s)")
for f in fails:
    say(f"  FAILED: {f}")
say("=" * 72)
print("WROTE", LOG)
