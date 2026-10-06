"""Verify the frozen build: bundled runtime/ffmpeg are found, transcribe works."""
import os
import subprocess
import sys
from pathlib import Path

DIST = Path(r"D:\Work\asr_mm\dist\asr-mm\asr-mm.exe")
VIDEO = r"D:\Work\asr_mm\samples/课堂录像示例.mp4"
MODELS = r"D:\Work\asr_mm\.asrhome\models"
LOG = Path(r"D:\Work\asr_mm\tools\dist_test.txt")

buf: list[str] = []


def run(args, env_extra=None, label=""):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env.pop("ASR_MM_HOME", None)
    if env_extra:
        env.update(env_extra)
    p = subprocess.run([str(DIST), *args], capture_output=True, env=env, timeout=1800)
    out = p.stdout.decode("utf-8", "replace").strip()
    err = p.stderr.decode("utf-8", "replace").strip()
    head = f"$ asr-mm {' '.join(args)}" + (f"   [{label}]" if label else "")
    body = head + "\n" + "=" * len(head) + "\n"
    if out:
        body += out + "\n"
    if err:
        body += "--- stderr ---\n" + err[:3000] + "\n"
    body += f"[exit {p.returncode}]\n\n"
    buf.append(body)
    LOG.write_text("".join(buf), encoding="utf-8")
    return p


# 1. clean profile: runtime + ffmpeg must come from the bundle, models absent
run(["--version"], label="version")
run(["doctor", VIDEO], label="clean profile: bundled runtime/ffmpeg resolved")
# 2. point at the already-downloaded models
run(["doctor", VIDEO], {"ASR_MM_HOME": r"D:\Work\asr_mm\.asrhome"},
    label="with models present")
# 3. real transcribe through the frozen binary
run(["transcribe", VIDEO, "-s", "00:00:15", "-e", "00:00:45",
     "-o", r"D:\Work\asr_mm\tools\dist_out", "--format", "txt,srt"],
    {"ASR_MM_HOME": r"D:\Work\asr_mm\.asrhome"},
    label="transcribe via frozen build")
# 4. error path still readable
run(["transcribe", VIDEO, "-s", "00:05:00", "-e", "00:06:00"],
    {"ASR_MM_HOME": r"D:\Work\asr_mm\.asrhome"}, label="error path")

print("DIST TEST DONE ->", LOG)
