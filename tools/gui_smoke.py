"""Drive the real GUI headlessly-ish: load video, transcribe, screenshot, report."""
import os
import sys
from pathlib import Path

os.environ.setdefault("ASR_MM_HOME", r"D:\Work\asr_mm\.asrhome")
sys.path.insert(0, r"D:\Work\asr_mm")

from PySide6.QtCore import QEventLoop, QTimer, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from asr_mm.gui.app import MainWindow  # noqa: E402

VIDEO = r"D:\Work\asr_mm\20250912 哲商現代実験学校 MR1 part1.avi"
SHOTS = Path(r"D:\Work\asr_mm\tools\shots")
SHOTS.mkdir(parents=True, exist_ok=True)
LOG = Path(r"D:\Work\asr_mm\tools\gui_report.txt")

log: list[str] = []
state = {"done": False, "failed": None, "shot": 0}


def say(msg: str) -> None:
    log.append(msg)
    LOG.write_text("\n".join(log), encoding="utf-8")


def wait(ms: int, loop: QEventLoop) -> None:
    t = QTimer()
    t.setSingleShot(True)
    t.timeout.connect(loop.quit)
    t.start(ms)
    loop.exec()


app = QApplication.instance() or QApplication(sys.argv)
win = MainWindow()
win.resize(1180, 820)
win.show()

say("1. window constructed")
win.load_video(Path(VIDEO))
say(f"2. video loaded: {win.lbl_file.text()}")

loop = QEventLoop()
wait(2000, loop)
say(f"3. playback ok = {win.player_ok}")
say(f"   player error = {win.player.errorString()!r}")
say(f"   preview visible = video={win.video.isVisible()} drop={win.drop.isVisible()}")

# narrow the range to 15s-45s the way a user would
win.spin_start.setTime(win.spin_start.time().fromString("00:00:15.000", "HH:mm:ss.zzz"))
win.spin_end.setTime(win.spin_end.time().fromString("00:00:45.000", "HH:mm:ss.zzz"))
wait(200, loop)
say(f"4. range = {win.slider.range()}")
win.grab().save(str(SHOTS / "1_loaded.png"))
say("5. screenshot 1_loaded.png")

win.run_transcribe()
say("6. transcribe started")
for _ in range(120):
    wait(500, loop)
    if win.worker is None:
        break
say(f"7. transcribe finished, status = {win.statusBar().currentMessage()}")

if win.result:
    say(f"   segments = {len(win.result.segments)}")
    for s in win.result.segments[:4]:
        say(f"   {s.start:.2f}-{s.end:.2f}  {s.text}")
    win.grab().save(str(SHOTS / "2_result.png"))
    say("8. screenshot 2_result.png")
    win.btn_clip.setEnabled(True)
else:
    say("   NO RESULT")
    say(f"   last error: {state['failed']}")

win.close()
say("9. done")
print("GUI SMOKE OK")
