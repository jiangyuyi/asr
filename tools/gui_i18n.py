"""Drive the real GUI in each language: load video, transcribe, screenshot."""
import os
import sys
from pathlib import Path

os.environ.setdefault("ASR_MM_HOME", r"D:\Work\asr_mm\.asrhome")
sys.path.insert(0, r"D:\Work\asr_mm")

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from asr_mm import i18n  # noqa: E402
from asr_mm.gui.app import MainWindow  # noqa: E402

VIDEO = r"D:\Work\asr_mm\课堂录像示例.mp4"
SHOTS = Path(r"D:\Work\asr_mm\tools\shots")
SHOTS.mkdir(parents=True, exist_ok=True)
LOG = Path(r"D:\Work\asr_mm\tools\gui_i18n.txt")

log: list[str] = []


def say(m):
    log.append(str(m))
    LOG.write_text("\n".join(log), encoding="utf-8")


def wait(ms, loop):
    t = QTimer()
    t.setSingleShot(True)
    t.timeout.connect(loop.quit)
    t.start(ms)
    loop.exec()


app = QApplication.instance() or QApplication(sys.argv)
win = MainWindow()
win.resize(1240, 840)
win.show()
win.raise_()
win.activateWindow()
loop = QEventLoop()
wait(600, loop)

codes = [c for c, _ in i18n.available_languages()]
say(f"languages: {codes}")
say(f"detected: {i18n.detect_system_language()}")

win.load_video(Path(VIDEO))
wait(2200, loop)
win.spin_start.setTime(win.spin_start.time().fromString("00:00:15.000", "HH:mm:ss.zzz"))
win.spin_end.setTime(win.spin_end.time().fromString("00:00:45.000", "HH:mm:ss.zzz"))
wait(300, loop)

for idx, code in enumerate(codes, 1):
    win.cmb_lang.setCurrentIndex(idx - 1)
    wait(500, loop)
    say(f"\n--- {code} ---")
    say(f"  window : {win.windowTitle()}")
    say(f"  run    : {win.btn_run.text()}")
    say(f"  section: {win.sec_range.text()} / {win.sec_options.text()} / {win.sec_results.text()}")
    say(f"  table  : {[win.table.horizontalHeaderItem(c).text() for c in range(3)]}")
    say(f"  menu   : {win.menu_file.title()} {win.menu_tools.title()} {win.menu_help.title()}")
    say(f"  langs  : {[win.cmb_lang.itemText(i) for i in range(win.cmb_lang.count())]}")

    # transcribe once per language to prove the pipeline survives a switch
    win.run_transcribe()
    for _ in range(120):
        wait(500, loop)
        if win.worker is None:
            break
    say(f"  status : {win.statusBar().currentMessage()}")
    say(f"  rows   : {win.table.rowCount()}")
    if win.table.rowCount():
        say(f"  row0   : {win.table.item(0, 2).text()[:70]}")
    shot = SHOTS / f"i18n_{code}.png"
    QGuiApplication.primaryScreen().grabWindow(0).save(str(shot))
    say(f"  shot   : {shot}")

# language switch must not lose the user's edits
win.cmb_lang.setCurrentIndex(0)
wait(400, loop)
item = win.table.item(0, 2)
if item:
    item.setText("人工修改过的文字 / edited by hand")
wait(200, loop)
win.cmb_lang.setCurrentIndex(2)
wait(400, loop)
after = win.table.item(0, 2)
say(f"\nedit survives language switch: {after.text() if after else 'NO ROW'}")
say(f"language now: {i18n.get_language()}")

win.close()
say("done")
print("GUI I18N OK")
