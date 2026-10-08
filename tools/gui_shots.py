"""Widget-level screenshots of the GUI in each language (docs use).

隐私说明：这里**不跑真实课堂录像**。docs/ 里的截图会出现在公开仓库首页，
而界面左上角显示的就是视频文件名、结果表里显示的就是转写原文——用真实素材
生成就等于把学校名和学生课堂内容公开出去。

所以本脚本：
  * 打开 samples/课堂录像示例.mp4（ffmpeg 生成的测试图 + 正弦音，无人声）
  * 往表格里注入**虚构**的示例句子，只为展示界面排版
  * 截三种语言的界面

换语言、换文案都不会让截图失真，因为截图展示的是界面本身。
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("ASR_MM_HOME", str(ROOT / ".asrhome"))
os.environ.setdefault("ASR_MM_RESOURCE_ROOT", str(ROOT / "packaging" / "payload"))
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from asr_mm import i18n  # noqa: E402
from asr_mm.gui.app import MainWindow  # noqa: E402
from asr_mm.transcribe import Segment, Transcript  # noqa: E402

VIDEO = ROOT / "samples" / "课堂录像示例.mp4"
DOCS = ROOT / "docs"
DOCS.mkdir(parents=True, exist_ok=True)


def ensure_sample_video() -> Path:
    """示例视频不入库（*.mp4 被 gitignore），需要时现生成。

    用 ffmpeg 的测试图 + 正弦音造一段 70 秒的片子：够长以便时间轴区间有意义，
    又不含任何真实内容。
    """
    if VIDEO.exists():
        return VIDEO
    import subprocess
    VIDEO.parent.mkdir(parents=True, exist_ok=True)
    exe = ROOT / "packaging" / "payload" / "ffmpeg" / (
        "ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    cmd = [str(exe), "-y",
           "-f", "lavfi", "-i", "testsrc2=size=640x480:rate=15:duration=70",
           "-f", "lavfi", "-i", "sine=frequency=300:duration=70",
           "-c:v", "mpeg4", "-q:v", "6", "-c:a", "aac", "-shortest",
           str(VIDEO)]
    subprocess.run(cmd, check=True, capture_output=True)
    print(f"已生成示例视频: {VIDEO}")
    return VIDEO

# 虚构的示例文本。不要用任何真实课堂录像的转写——这些句子是手写的，
# 目的是让截图里的表格看起来有内容、有长短差异。
SAMPLE = [
    (15.3, 25.3, "请把这份材料复印三份，其中一部分留给我自己用。"),
    (27.35, 37.35, "因为前面那条路正在维修，公交车今天临时改道绕行。"),
    (37.35, 44.98, "你觉得这个价格合理吗？如果不合适可以再商量。"),
    (48.10, 56.40, "这批设备的保修期是两年，过期之后需要重新购买。"),
    (58.00, 66.20, "好的，我稍后把详细的情况整理好发给你。"),
]


def fake_transcript() -> Transcript:
    segs = [Segment(a, b, text) for a, b, text in SAMPLE]
    return Transcript(
        source=str(VIDEO), source_duration=70.0,
        range_start=15.0, range_end=45.0,
        applied_start=15.0, applied_end=45.0,
        model="nano", model_label="Nano（质量档·推荐）",
        segments=segs, elapsed=2.9, audio_seconds=30.0,
    )


app = QApplication.instance() or QApplication(sys.argv)

# Qt6 不再自带字体，离屏模式下会找不到任何中文字体，整张截图变成豆腐块。
# 显式加载系统里的中文字体，否则截图没法用。
def load_cjk_font() -> str:
    from PySide6.QtGui import QFont, QFontDatabase
    for name in ("msyh.ttc", "msjh.ttc", "simsun.ttc", "simhei.ttf",
                 "Deng.ttf", "mingliub.ttc"):
        path = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / name
        if path.exists():
            fid = QFontDatabase.addApplicationFont(str(path))
            families = QFontDatabase.applicationFontFamilies(fid)
            if families:
                f = QFont(families[0], 10)
                app.setFont(f)
                return families[0]
    return ""


print("CJK font:", load_cjk_font() or "(未找到)")

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
win.load_video(ensure_sample_video())
wait(2000)
win.spin_start.setTime(win.spin_start.time().fromString("00:00:15.000", "HH:mm:ss.zzz"))
win.spin_end.setTime(win.spin_end.time().fromString("00:00:45.000", "HH:mm:ss.zzz"))
wait(200)

names = {"zh": "screenshot.png", "en": "screenshot-en.png", "ja": "screenshot-ja.png"}
for idx, (code, _native) in enumerate(i18n.available_languages()):
    win.cmb_lang.setCurrentIndex(idx)
    wait(400)
    # 界面是真的，文字是虚构的：直接注入结果而不跑识别。
    win.result = fake_transcript()
    win._fill_table(win.result)
    # 填表/加载视频过程中可能留下一个选中的单元格，截图里会是一块蓝底，
    # 看着像出了错。README 首图不该有这种东西。
    win.table.clearSelection()
    win.table.setCurrentCell(-1, -1)
    win.table.setFocus()
    for b in (win.btn_copy, win.btn_save, win.btn_clip):
        b.setEnabled(True)
    win.btn_run.setEnabled(True)
    win.statusBar().showMessage(
        f"示例：{len(win.result.segments)} 条片段，耗时 2.9s / 音频 30s（10×）")
    wait(300)
    out = DOCS / names[code]
    win.grab().save(str(out))
    print(f"{code} -> {out}  ({out.stat().st_size // 1024} KB)  "
          f"rows={win.table.rowCount()}")

win.close()
print("SHOTS DONE")
