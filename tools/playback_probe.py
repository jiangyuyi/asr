"""视频播放诊断：Qt6 多媒体后端到底能不能解这个文件。

背景：1.5.0 用户反馈视频放不出来。真实素材是 MJPEG/AVI + PCM，界面里用的是
QMediaPlayer + QVideoWidget。这里不开窗口，只探测后端能力，把结论落到具体原因。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QEventLoop, QTimer, Qt  # noqa: E402
from PySide6.QtGui import QFont, QFontDatabase  # noqa: E402
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

VIDEO = ROOT / "samples" / "课堂录像示例.mp4"
SAMPLE = ROOT / "samples" / "课堂录像示例.mp4"

app = QApplication.instance() or QApplication(sys.argv[:1])
for _n in ("msyh.ttc", "simsun.ttc", "simhei.ttf"):
    _p = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / _n
    if _p.exists():
        _f = QFontDatabase.applicationFontFamilies(
            QFontDatabase.addApplicationFont(str(_p)))
        if _f:
            app.setFont(QFont(_f[0], 10))
            break

print("Qt 版本:", __import__("PySide6.QtCore", fromlist=["qVersion"]).qVersion())

ERROR_NAMES = ["NoError", "Reserved", "UnknownError", "ResourceError",
               "DecodingError", "NetworkError", "ExtraValueError"]


def _err_name(e) -> str:
    try:
        return e.name
    except AttributeError:
        return f"Error({int(e.value)})" if hasattr(e, "value") else str(e)


def probe(path: Path, seconds: float = 6.0) -> None:
    print(f"\n=== {path.name} ===")
    if not path.exists():
        print("  文件不存在")
        return
    p = QMediaPlayer()
    aout = QAudioOutput()
    p.setAudioOutput(aout)
    state = {"err": None, "dur": None, "pos": 0, "frames": 0}
    loop = QEventLoop()

    def on_err(e, msg=""):
        if _err_name(e) != "NoError":
            state["err"] = f"{_err_name(e)}: {msg}"
            loop.quit()

    def on_dur(d):
        if d > 0:
            state["dur"] = d / 1000.0

    def on_pos(pos):
        state["pos"] = pos

    p.errorOccurred.connect(on_err)
    p.durationChanged.connect(on_dur)
    p.positionChanged.connect(on_pos)
    p.mediaStatusChanged.connect(
        lambda s: loop.quit() if s in (
            QMediaPlayer.MediaStatus.InvalidMedia,
            QMediaPlayer.MediaStatus.EndOfMedia) else None)
    p.setSource(QUrl.fromLocalFile(str(path)))
    p.play()

    t = QTimer()
    t.setSingleShot(True)
    t.timeout.connect(loop.quit)
    t.start(int(seconds * 1000))
    loop.exec()

    print(f"  错误        : {state['err'] or '无'}")
    print(f"  时长        : {state['dur']}")
    print(f"  播放位置    : {state['pos']/1000:.2f}s")
    print(f"  播放状态    : {p.playbackState()}")
    print(f"  媒体状态    : {p.mediaStatus()}")
    ok = state["err"] is None and state["dur"] and state["pos"] > 0
    print(f"  结论        : {'能播 ✓' if ok else '放不出来 ✗'}")
    p.stop()


from PySide6.QtCore import QUrl  # noqa: E402

for v in (VIDEO, SAMPLE):
    probe(v)
