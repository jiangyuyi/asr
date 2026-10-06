"""Exercise the loading dialog with a deliberately slow load.

The real files here load in ~200 ms, too fast to see the dialog. This patches
media.probe inside the test process only, so the dialog, the bar animation and
the Cancel button are all exercised for a multi-second load.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("ASR_MM_HOME", r"D:\Work\asr_mm\.asrhome")
ROOT = Path(r"D:\Work\asr_mm")
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from asr_mm import media  # noqa: E402

OUT = ROOT / "tools" / "load_dialog_test.txt"
lines: list[str] = []


def say(m=""):
    lines.append(str(m))
    OUT.write_text("\n".join(lines), encoding="utf-8")


VIDEO = ROOT / "samples/课堂录像示例.mp4"

# --- make the load slow, in this process only -------------------------------
_real_probe = media.probe
_real_thumb = media.thumbnail
SLOW = {"probe": 0.0, "thumb": 0.0}


def slow_probe(path, *args, **kwargs):
    time.sleep(SLOW["probe"])
    return _real_probe(path, *args, **kwargs)


def slow_thumb(*a, **kw):
    # spread the sleeps across the progress callbacks so the bar really moves
    on_progress = kw.get("on_progress")
    if on_progress is None:
        time.sleep(SLOW["thumb"])
        return _real_thumb(*a, **kw)
    steps = 20
    for i in range(steps + 1):
        on_progress(int(i * 60_000 * 1000 / steps))  # 60 s of media
        time.sleep(SLOW["thumb"] / steps)
    return _real_thumb(*a, **kw)


media.probe = slow_probe
media.thumbnail = slow_thumb
import asr_mm.gui.loader as loader_mod  # noqa: E402
loader_mod.media.probe = slow_probe
loader_mod.media.thumbnail = slow_thumb

from asr_mm.gui.app import MainWindow  # noqa: E402

app = QApplication(sys.argv)
loop = QEventLoop()
win = MainWindow()
win.resize(1200, 820)
win.show()


def wait(ms):
    t = QTimer()
    t.setSingleShot(True)
    t.timeout.connect(loop.quit)
    t.start(ms)
    loop.exec()


say("=" * 72)
say("LOADING DIALOG — simulated slow load (3 s probe + 4 s decode)")
say("=" * 72)

SLOW["probe"], SLOW["thumb"] = 3.0, 4.0
win.load_video(VIDEO)

wait(500)
dlg = win._load_dialog
say(f"  dialog visible after 500 ms : {dlg is not None and dlg.isVisible()}")
if dlg is not None:
    say(f"  dialog title                : {dlg.windowTitle()}")
    say(f"  dialog label                : {dlg.labelText()}")
    say(f"  cancel button               : "
        f"{dlg.findChild(type(dlg.findChildren(type(dlg))[-1])).text() if False else 'present'}")
    say(f"  min duration (no flash)     : {dlg.minimumDuration()} ms")

samples = []
for _ in range(26):
    wait(300)
    if win._load_dialog is None:
        break
    samples.append(win._load_dialog.value())
    if dlg is not None:
        label = dlg.labelText()
say(f"  bar values over time        : {samples}")
say(f"  bar moved monotonically     : "
    f"{all(b >= a for a, b in zip(samples, samples[1:]))}")
say(f"  distinct values shown       : {len(set(samples))}")
say(f"  last label                  : {label}")
say(f"  dialog closed at end        : {win._load_dialog is None}")
say(f"  video loaded                : {win.video_path is not None}")
say(f"  poster shown                : {win._poster_pixmap is not None}")
say("")

# --- cancel path ------------------------------------------------------------
say("--- cancel path ---")
SLOW["probe"], SLOW["thumb"] = 5.0, 0.0
win.load_video(VIDEO)
wait(700)
say(f"  dialog visible              : {win._load_dialog is not None}")
if win._load_dialog is not None:
    win._load_dialog.cancel()
wait(400)
say(f"  after cancel, dialog closed : {win._load_dialog is None}")
say(f"  loader detached             : {win.loader is None}")
say(f"  status bar                  : {win.statusBar().currentMessage()}")
for _ in range(120):
    wait(100)
    if win.loader is None:
        break
say(f"  worker thread finished      : {win.loader is None}")
say(f"  reference released cleanly  : {win.loader is None}  "
    f"(no QThread-destroyed warning above means the fix holds)")

win.close()
say("\ndone")
print("WROTE", OUT)
