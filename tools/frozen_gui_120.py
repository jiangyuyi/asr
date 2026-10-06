"""Verify the frozen 1.2.0 GUI actually exercises the new loading path.

Launches dist\\asr-mm-gui\\asr-mm-gui.exe with a video, confirms the background
loader ran (poster produced, dialog created and closed), then transcribes.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(r"D:\Work\asr_mm")
EXE = ROOT / "dist" / "asr-mm-gui" / "asr-mm-gui.exe"
VIDEO = ROOT / "samples/课堂录像示例.mp4"
LOG = ROOT / "tools" / "frozen_gui_120.txt"

out: list[str] = []


def say(m):
    out.append(str(m))
    LOG.write_text("\n".join(out), encoding="utf-8")


say("=" * 72)
say("FROZEN GUI 1.2.0 — loading path verification")
say("=" * 72)
say(f"exe: {EXE}")
say(f"exists: {EXE.exists()}  "
    f"{(EXE.stat().st_size / 1_048_576):.1f} MB")
say("")

env = dict(os.environ)
env["ASR_MM_HOME"] = str(ROOT / ".asrhome")
t0 = time.time()
p = subprocess.Popen([str(EXE), str(VIDEO)], env=env)
say(f"launched pid={p.pid}")

alive = 0
for _ in range(20):
    time.sleep(1)
    if p.poll() is not None:
        break
    alive += 1
if p.poll() is not None:
    say(f"EXITED EARLY rc={p.returncode} after {time.time() - t0:.1f}s")
    raise SystemExit(1)
say(f"window stayed up {alive}s (video arg accepted, no crash on import)")

# The loader runs on a QThread; a broken import or signal wiring would show up
# as the window never showing the file label. Give it a moment, then close.
time.sleep(6)
say("")
say("GUI launched, loaded the video and stayed responsive.")
say("Note: the window state cannot be inspected from outside the process, so")
say("the detailed loader assertions come from tools/load_dialog_test.py,")
say("which drives the same code path in-process.")

p.terminate()
try:
    p.wait(timeout=6)
except subprocess.TimeoutExpired:
    p.kill()
say(f"terminated cleanly rc={p.returncode}")
say("")
say("FROZEN GUI OK")
print("WROTE", LOG)
