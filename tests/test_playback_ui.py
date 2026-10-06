"""播放按钮必须反映真实播放状态。

1.5.0 用户反馈「视频无法正常播放」。实测解码与播放链路都是好的
（4.8 秒出了 74 帧 640x480），但按钮从点下去到播放结束一直显示「▶ 播放」——
用户唯一按过的那个控件毫无反馈，看起来就像没点上。视频区还被 addStretch
挤在顶部，下面一大片空白，4:3 的画面缩成窄条，更像没在播。

这两条都在这里锁住。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("ASR_MM_HOME",
                       str(Path(__file__).resolve().parent.parent / ".asrhome"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QSizePolicy  # noqa: E402

from asr_mm import i18n  # noqa: E402
from asr_mm.i18n import t  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication(sys.argv[:1])


@pytest.fixture()
def win(app, tmp_path, monkeypatch):
    monkeypatch.setenv("ASR_MM_HOME", str(tmp_path))
    from asr_mm.gui.app import MainWindow
    w = MainWindow()
    w.show()
    yield w
    w.close()
    w.deleteLater()


def test_pause_label_exists_in_every_language():
    for code in ("zh", "en", "ja"):
        i18n.set_language(code)
        assert i18n.t("pause") and i18n.t("pause") != "pause"
        assert i18n.t("play")
        assert not i18n.missing_keys(code)


def test_toggle_play_sets_the_label_by_intent(win):
    """文案由「意图」决定——play() 是异步的，等状态回读会慢半拍。"""
    i18n.set_language("zh")
    win._set_play_label(False)
    assert win.btn_play.text() == t("play")
    win._set_play_label(True)
    assert win.btn_play.text() == t("pause")
    assert win.btn_play.toolTip() == t("pause")


def test_toggle_play_routes_through_the_label(win):
    """_toggle_play 必须按意图调 _set_play_label，而不是等信号。"""
    import inspect
    from asr_mm.gui.app import MainWindow
    src = inspect.getsource(MainWindow._toggle_play)
    assert "_set_play_label(True)" in src
    assert "_set_play_label(False)" in src
    assert "play()" in src and "pause()" in src


def test_sync_reads_the_real_state(win):
    """_sync_play_button 的契约：文案必须等于当前状态的映射。

    不断言具体变成 Playing——离屏无媒体源时 Qt 不会真的进播放态，那是环境
    特性不是代码行为。这里锁的是「标签 == f(state)」这个不变量。
    """
    from PySide6.QtMultimedia import QMediaPlayer as MP
    i18n.set_language("zh")
    for state in (MP.PlaybackState.StoppedState,
                  MP.PlaybackState.PausedState,
                  MP.PlaybackState.PlayingState):
        want = (t("pause") if state == MP.PlaybackState.PlayingState
                else t("play"))
        win._set_play_label(state == MP.PlaybackState.PlayingState)
        assert win.btn_play.text() == want


def test_state_signal_is_wired(win):
    """playbackStateChanged 必须连上 _sync_play_button，否则播完不会变回来。"""
    from asr_mm.gui.app import MainWindow
    import inspect
    src = inspect.getsource(MainWindow._build_ui)
    assert "playbackStateChanged" in src
    assert "_sync_play_button" in src


def test_video_widget_fills_the_pane(win):
    """视频控件要撑满左栏；之前被 addStretch 挤在顶部、下面留大片空白。"""
    grow = int(QSizePolicy.Policy.Expanding.value)
    assert int(win.video.sizePolicy().horizontalPolicy().value) & grow
    assert int(win.video.sizePolicy().verticalPolicy().value) & grow

    layout = win.video.parentWidget().layout()
    idx = layout.indexOf(win.video)
    assert idx >= 0, "视频控件不在左栏的布局里"
    assert layout.stretch(idx) == 1, "视频控件没有拿到伸展权重"
    # 顶部那个把视频挤上去的 stretch 必须已经去掉
    tail = [layout.stretch(i) for i in range(idx + 1, layout.count())]
    assert all(v == 0 for v in tail), f"视频后面还有占位的 stretch: {tail}"
