"""在真实窗口里跑一遍播放流程，看应用自己怎么判断能不能播。

offscreen 模式下 QVideoWidget 渲染不出画面（没有 GPU），所以必须用真实
platform plugin，否则会把"截图是白的"误判成播放失败。
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
SHOT = ROOT / "build_playback_shot.png"

app = QApplication.instance() or QApplication(sys.argv[:1])
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


wait(600)
print(f"视频: {VIDEO.name}")
win.load_video(VIDEO)
wait(3000)          # 等后台加载 + 1.2s 后的 _confirm_playback

print(f"  player_ok        : {win.player_ok}")
print(f"  播放按钮可用      : {win.btn_play.isEnabled()}")
print(f"  播放按钮文案      : {win.btn_play.text()!r}")
print(f"  player.error()   : {win.player.error()}")
print(f"  player.errorString(): {win.player.errorString()!r}")
print(f"  媒体状态          : {win.player.mediaStatus()}")
print(f"  video 可见        : {win.video.isVisible()}  大小 {win.video.width()}x{win.video.height()}")
print(f"  drop 可见         : {win.drop.isVisible()}")
print(f"  海报已缓存        : {win._poster_pixmap is not None}")
print(f"  状态栏            : {win.statusBar().currentMessage()[:70]!r}")

if win.btn_play.isEnabled():
    before = win.player.position()
    win.btn_play.click()
    wait(4000)
    after = win.player.position()
    print(f"  点播放后位置       : {before} -> {after} ms  "
          f"{'在推进 ✓' if after > before + 500 else '没动 ✗'}")
    print(f"  播放状态           : {win.player.playbackState()}")
    print(f"  播放中按钮文案     : {win.btn_play.text()!r}")
else:
    print("  播放按钮不可用，无法测试实际播放")

wait(500)
SHOT.parent.mkdir(exist_ok=True)
win.grab().save(str(SHOT))
print(f"  截图: {SHOT}  ({SHOT.stat().st_size//1024} KB)")
win.close()
print("DONE")
