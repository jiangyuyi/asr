"""Widget-level screenshots of the GUI in each language (docs use)."""
import os
import sys
from pathlib import Path

os.environ.setdefault("ASR_MM_HOME", r"D:\Work\asr_mm\.asrhome")
sys.path.insert(0, r"D:\Work\asr_mm")

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from asr_mm import i18n  # noqa: E402
from asr_mm.gui.app import MainWindow  # noqa: E402

VIDEO = r"D:\Work\asr_mm\课堂录像示例.mp4"
DOCS = Path(r"D:\Work\asr_mm\docs")
DOCS.mkdir(parents=True, exist_ok=True)

app = QApplication.instance() or QApplication(sys.argv)
win = MainWindow()
win.resize(1240, 860)
win.show()
loop = QEventLoop()


def wait(ms):
    t = QTimer()
    t.setSingleShot(True)
    t.timeout.connect(loop.quit)
    t.start(ms)
    loop.exec()


wait(500)
win.load_video(Path(VIDEO))
wait(2000)
win.spin_start.setTime(win.spin_start.time().fromString("00:00:15.000", "HH:mm:ss.zzz"))
win.spin_end.setTime(win.spin_end.time().fromString("00:00:45.000", "HH:mm:ss.zzz"))
wait(200)

names = {"zh": "screenshot.png", "en": "screenshot-en.png", "ja": "screenshot-ja.png"}
for idx, (code, native) in enumerate(i18n.available_languages()):
    win.cmb_lang.setCurrentIndex(idx)
    wait(400)
    win.run_transcribe()
    for _ in range(120):
        wait(500)
        if win.worker is None:
            break
    wait(300)
    out = DOCS / names[code]
    win.grab().save(str(out))
    print(f"{code} -> {out}  ({out.stat().st_size // 1024} KB)  "
          f"rows={win.table.rowCount()}")

win.close()
print("SHOTS DONE")
