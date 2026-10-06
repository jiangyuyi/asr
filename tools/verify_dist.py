"""Compare frozen-build output with the dev run, then launch the packaged GUI."""
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(r"D:\Work\asr_mm")
DIST = ROOT / "dist" / "asr-mm" / "asr-mm.exe"
DEV = ROOT / "tools" / "e2e" / "slice"
FROZEN = ROOT / "tools" / "dist_out"
LOG = ROOT / "tools" / "verify.txt"
buf: list[str] = []


def say(m):
    buf.append(str(m))
    LOG.write_text("\n".join(buf), encoding="utf-8")


def read_srt(p: Path) -> str:
    return p.read_text(encoding="utf-8").strip() if p.exists() else ""


dev = next(DEV.glob("*.srt"), None)
frozen = next(FROZEN.glob("*.srt"), None)
say("=== frozen vs dev SRT (15s-45s, nano) ===")
a, b = read_srt(dev), read_srt(frozen)
say(f"dev    : {dev.name}")
say(f"frozen : {frozen.name}")
say(f"identical: {a == b}")
if a != b:
    say("--- dev ---"); say(a)
    say("--- frozen ---"); say(b)
else:
    say(a)

# launch the packaged GUI, let it load, screenshot the screen
say("\n=== launching packaged GUI ===")
env = dict(os.environ)
env["ASR_MM_HOME"] = str(ROOT / ".asrhome")
proc = subprocess.Popen([str(ROOT / "dist" / "asr-mm-gui" / "asr-mm-gui.exe"),
                         str(ROOT / "samples/课堂录像示例.mp4")],
                        env=env)
say(f"pid = {proc.pid}")
time.sleep(14)
alive = proc.poll() is None
say(f"still running after 14s: {alive}")

if alive:
    shot = Path(r"D:\Work\asr_mm\tools\shots\4_dist_gui.png")
    cap = subprocess.run(
        [sys.executable, "-c",
         "import sys;from PySide6.QtWidgets import QApplication;"
         "from PySide6.QtGui import QGuiApplication;"
         "a=QApplication(sys.argv);"
         f"QGuiApplication.primaryScreen().grabWindow(0).save(r'{shot}');print('ok')"],
        capture_output=True)
    say(f"screenshot -> {shot}  {cap.stdout.decode(errors='replace').strip()}")
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
say("done")
print("VERIFY DONE")
