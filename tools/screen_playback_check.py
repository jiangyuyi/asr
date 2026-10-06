"""抓真实屏幕的视频区域，判断 QVideoWidget 到底画没画。

要点：
  * 用 QScreen.grabWindow(0) 抓合成后的桌面——QWidget.grab() 抓不到
    QVideoWidget 的原生子窗口。
  * 裁出视频控件那块，对比「加载后（海报）」和「播放中（真实帧）」的像素统计。
    全黑 = 没画面；均值/方差明显偏离纯黑 = 有东西在画。
  * 每次抓屏前把窗口顶到最前，否则会被别的窗口盖住（上一轮就吃过这个亏）。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.pop("QT_QPA_PLATFORM", None)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("ASR_MM_HOME", str(ROOT / ".asrhome"))
os.environ.setdefault("ASR_MM_RESOURCE_ROOT", str(ROOT / "packaging" / "payload"))

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from asr_mm.gui.app import MainWindow  # noqa: E402

VIDEO = Path(sys.argv[1]) if len(sys.argv) > 1 else (
    ROOT / "samples" / "课堂录像示例.mp4")
OUT = ROOT / "build_screen_shot"
OUT.mkdir(exist_ok=True)

app = QApplication.instance() or QApplication(sys.argv[:1])
win = MainWindow()
win.resize(1240, 860)
loop = QEventLoop()


def wait(ms):
    t = QTimer()
    t.setSingleShot(True)
    t.timeout.connect(loop.quit)
    t.start(ms)
    loop.exec()


def front():
    win.show()
    win.raise_()
    win.activateWindow()
    win.setFocus()
    wait(500)


def video_stats(tag):
    """把视频区域从整屏截图里裁出来，存盘 + 给像素统计。"""
    front()
    pm = app.primaryScreen().grabWindow(0)
    tl = win.video.mapToGlobal(win.video.rect().topLeft())
    w, h = win.video.width(), win.video.height()
    crop = pm.copy(tl.x(), tl.y(), w, h)
    p = OUT / f"video-{tag}.png"
    crop.save(str(p))
    img = crop.toImage().convertToFormat(crop.toImage().Format.Format_RGB32)
    vals = []
    step = max(1, (img.width() * img.height()) // 40000)
    data = img.bits().tobytes()
    for i in range(0, len(data) - 3, 4 * step):
        vals.append((data[i], data[i + 1], data[i + 2]))
    n = len(vals) or 1
    mean = sum(sum(v) for v in vals) / (3 * n)
    var = sum((sum(v) / 3 - mean) ** 2 for v in vals) / n
    nonblack = sum(1 for v in vals if max(v) > 24) / n
    print(f"  [{tag}] {w}x{h}  均值={mean:6.2f}  方差={var:7.2f}  "
          f"非黑像素占比={nonblack*100:5.1f}%  -> {p.name}")
    return mean, var, nonblack


front()
win.load_video(VIDEO)
wait(3000)
print(f"  player_ok={win.player_ok}  错误={win.player.errorString()!r}")
before = video_stats("loaded")

if win.btn_play.isEnabled():
    win.btn_play.click()
    wait(3000)
    print(f"  播放中：位置={win.player.position()}ms  文案={win.btn_play.text()!r}")
    after = video_stats("playing")
    print()
    verdict = ("画面在变（有帧）✓" if after[2] > 0.05 and after[0] > 8
               else "画面仍是黑的/没变化 ✗")
    print(f"  结论: {verdict}")
    print(f"    加载后 非黑占比={before[2]*100:.1f}%  播放中 非黑占比={after[2]*100:.1f}%")
else:
    print("  播放按钮不可用")

win.close()
print("DONE")
