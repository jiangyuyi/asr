"""Prove the load path no longer freezes the GUI and reports real progress.

Runs the new LoadWorker against several files while a 20 ms heartbeat watches
the event loop, and records the progress values the dialog would show.
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

from asr_mm.gui.app import MainWindow  # noqa: E402
from asr_mm.gui.loader import LoadWorker  # noqa: E402

OUT = ROOT / "tools" / "load_progress_test.txt"
lines: list[str] = []


def say(m=""):
    lines.append(str(m))
    OUT.write_text("\n".join(lines), encoding="utf-8")


SMALL = ROOT / "课堂录像示例.mp4"
BIG = ROOT / "tools" / "big_sample.mp4"
JP = ROOT / "tools" / "日本語" / "テスト動画.avi"

app = QApplication(sys.argv)
loop = QEventLoop()
win = MainWindow()
win.resize(1200, 820)
win.show()

st = {"n": 0, "last": 0.0, "max": 0.0}
heart = QTimer()
heart.setInterval(20)


def tick():
    now = time.time()
    gap = now - st["last"]
    if st["n"] and gap > st["max"]:
        st["max"] = gap
    st["last"] = now
    st["n"] += 1


heart.timeout.connect(tick)
heart.start()


def wait(ms):
    t = QTimer()
    t.setSingleShot(True)
    t.timeout.connect(loop.quit)
    t.start(ms)
    loop.exec()


if JP.exists() is False and SMALL.exists():
    JP.parent.mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.copy2(SMALL, JP)

say("=" * 72)
say("LOAD PROGRESS / RESPONSIVENESS TEST")
say("=" * 72)
say("heartbeat = 20 ms; a stall is any gap far above that")
say("")

for label, path in (("50 MB AVI", SMALL), ("2 GB MP4", BIG),
                    ("日本語ファイル名.avi", JP)):
    if not path.exists():
        continue
    seen: list[float] = []
    state = {"done": None, "fail": None}

    st.update(n=0, last=time.time(), max=0.0)
    t0 = time.time()
    worker = LoadWorker(str(path), win)
    worker.progress.connect(lambda f, k: seen.append(f))
    worker.done.connect(lambda r: state.update(done=r))
    worker.failed.connect(lambda m: state.update(fail=m))
    worker.start()
    for _ in range(200):
        wait(50)
        if state["done"] or state["fail"] or not worker.isRunning():
            break
    elapsed = time.time() - t0
    worker.wait(3000)

    say(f"  {label}")
    say(f"    finished in            : {elapsed * 1000:7.0f} ms")
    say(f"    event-loop heartbeats  : {st['n']}")
    say(f"    WORST GUI-thread stall : {st['max'] * 1000:7.0f} ms")
    if state["fail"]:
        say(f"    FAILED: {state['fail']}")
    else:
        res = state["done"]
        say(f"    duration read          : {res.info.duration:.2f}s")
        say(f"    poster extracted       : {res.poster is not None}")
    say(f"    progress updates       : {len(seen)}"
        + (f"  -> {[f'{v * 100:.0f}%' for v in seen[:8]]}" if seen else ""))
    say("")

# The dialog itself must appear and close without stranding itself
say("--- dialog lifecycle through MainWindow.load_video() ---")
seen2: list[float] = []
win.statusBar().messageChanged.connect(lambda m: seen2.append(0.0) if "读取" in m or "Reading" in m or "デコード" in m else None)
win.load_video(SMALL)
wait(400)
say(f"    dialog visible right after call : {win._load_dialog is not None}")
seen_dialog = []
orig = win._load_dialog
for _ in range(200):
    wait(50)
    if win._load_dialog is None:
        break
say(f"    dialog still open after 400 ms  : {win._load_dialog is not None}")
for _ in range(100):
    wait(50)
    if win._load_dialog is None:
        break
say(f"    dialog closed when done        : {win._load_dialog is None}")
say(f"    video loaded                   : {win.video_path is not None}")
say(f"    poster shown                   : {win._poster_pixmap is not None}")
say(f"    duration                       : "
    f"{win.info.duration:.2f}s" if win.info else "n/a")
say(f"    status bar                     : {win.statusBar().currentMessage()}")
win.close()
say("")
say("done")
print("WROTE", OUT)
