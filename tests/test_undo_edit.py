"""每行撤销按钮：把手动改过的单元格恢复成引擎产出的原样。

改错字是常事——听错了、标点不对、译文想调顺。但「改回去」在表格里没有
入口，用户只能凭记忆重打一遍。这一版给每一行加一个撤销按钮，动过的行才亮，
并且撤销前必须确认、且要把改前改后并排列出来。

这里锁的是三件事：按钮只在该亮的时候亮、恢复的是**引擎原样**而不是上一版、
以及确认框真的把要丢的东西显示出来了。
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

from PySide6.QtWidgets import QApplication  # noqa: E402

from asr_mm import i18n, transcribe  # noqa: E402
from asr_mm.gui.app import (  # noqa: E402
    COL_EN, COL_JA, COL_TEXT, COL_UNDO, MainWindow,
)

# 手写的虚构句子，不要用真实课堂录像的转写。
SEGMENTS = [
    "今天的会议改到明天下午三点钟。",
    "请把这份材料复印三份。",
    "你觉得这个价格合理吗？",
]
EN = [
    "The meeting has been moved to 3 p.m. tomorrow.",
    "Please make three copies of this material.",
    "Do you think the price is reasonable?",
]


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication(sys.argv[:1])


@pytest.fixture()
def win(app, tmp_path, monkeypatch):
    monkeypatch.setenv("ASR_MM_HOME", str(tmp_path))
    from asr_mm.gui.app import MainWindow as MW
    w = MW()
    w.show()
    yield w
    w.close()
    w.deleteLater()


def _result():
    segs = [transcribe.Segment(i * 3.0, i * 3.0 + 2.0, s)
            for i, s in enumerate(SEGMENTS)]
    return transcribe.Transcript(
        source="sample.mp4", source_duration=30.0,
        range_start=0.0, range_end=9.0,
        applied_start=0.0, applied_end=9.0,
        model="nano", model_label="Nano",
        segments=segs, elapsed=1.0, audio_seconds=9.0,
    )


def _fill(win, translated: bool = False):
    """填表，可选地连译文一起填上。"""
    win._on_done(_result())
    if translated:
        win.translations = {"en": list(EN)}
        win._fill_table(win.result)


def _btn(win, row):
    return win.table.cellWidget(row, COL_UNDO)


def test_table_has_an_undo_column_and_a_button_per_row(win):
    _fill(win)
    assert win.table.columnCount() == 6, "撤销列没加上"
    assert win.table.horizontalHeaderItem(COL_UNDO) is not None
    for row in range(len(SEGMENTS)):
        assert _btn(win, row) is not None, f"第 {row} 行没有撤销按钮"


def test_button_is_disabled_until_the_row_is_edited(win):
    """没动过的行按了也没意义——按钮就该是灭的。"""
    _fill(win)
    for row in range(len(SEGMENTS)):
        assert not _btn(win, row).isEnabled(), \
            f"第 {row} 行没被编辑，按钮不该可点"


def test_editing_a_cell_lights_only_that_row(win):
    _fill(win)
    win.table.item(1, COL_TEXT).setText("请把这份材料复印一份。")
    assert _btn(win, 1).isEnabled(), "改过的行按钮没亮"
    assert not _btn(win, 0).isEnabled(), "没改的行被误点亮"
    assert not _btn(win, 2).isEnabled(), "没改的行被误点亮"


def test_undo_restores_the_engine_output(win, monkeypatch):
    """恢复的是识别结果本身，不是上一版，也不是空。"""
    _fill(win)
    win.table.item(0, COL_TEXT).setText("今天开会。")
    monkeypatch.setattr(MainWindow, "_confirm_undo", lambda *a: True)
    win._on_undo_clicked(0)
    assert win.table.item(0, COL_TEXT).text() == SEGMENTS[0]
    assert not _btn(win, 0).isEnabled(), "恢复后按钮该灭掉"


def test_undo_also_restores_an_edited_translation(win, monkeypatch):
    _fill(win, translated=True)
    assert win.table.item(0, COL_EN).text() == EN[0]
    win.table.item(0, COL_EN).setText("The meeting is tomorrow.")
    monkeypatch.setattr(MainWindow, "_confirm_undo", lambda *a: True)
    win._on_undo_clicked(0)
    assert win.table.item(0, COL_EN).text() == EN[0], \
        "译文应恢复成刚翻译出来的样子"


def test_undo_restores_every_edited_column_in_one_go(win, monkeypatch):
    _fill(win, translated=True)
    win.table.item(1, COL_TEXT).setText("复印两份。")
    win.table.item(1, COL_EN).setText("Please copy it.")
    monkeypatch.setattr(MainWindow, "_confirm_undo", lambda *a: True)
    win._on_undo_clicked(1)
    assert win.table.item(1, COL_TEXT).text() == SEGMENTS[1]
    assert win.table.item(1, COL_EN).text() == EN[1]


def test_cancelling_the_dialog_changes_nothing(win, monkeypatch):
    """确认框选「取消」时一个字都不能动。"""
    _fill(win)
    win.table.item(2, COL_TEXT).setText("这个价格合适吗？")
    monkeypatch.setattr(MainWindow, "_confirm_undo", lambda *a: False)
    win._on_undo_clicked(2)
    assert win.table.item(2, COL_TEXT).text() == "这个价格合适吗？"
    assert _btn(win, 2).isEnabled(), "取消后按钮该仍然亮着"


def test_confirm_dialog_lists_both_versions(win):
    """确认框必须把改前改后都列出来，否则用户是在盲点 destructive 操作。"""
    _fill(win)
    win.table.item(0, COL_TEXT).setText("今天开会。")
    pairs = [(COL_TEXT, "今天开会。", SEGMENTS[0])]
    text = win._undo_diff_text(pairs)
    assert SEGMENTS[0] in text, "确认框没有显示最初的内容"
    assert "今天开会。" in text, "确认框没有显示当前的内容"
    assert i18n.t("undo.irreversible") in text, \
        "确认框没说明恢复后不可再撤销"
    assert i18n.t("table.col_text") in text, "确认框没说明是哪一列"


def test_empty_original_is_shown_as_a_placeholder(win):
    """没翻译过的那两列初始是空的，得显示成「（空）」而不是留白。"""
    _fill(win)
    text = win._undo_diff_text([(COL_JA, "テスト", "")])
    assert i18n.t("undo.empty") in text


def test_re_translating_moves_the_baseline(win):
    """重新翻译后，「最初」就该是新的译文，否则撤销会把用户退回旧翻译。"""
    _fill(win, translated=True)
    win.table.item(0, COL_EN).setText("My edit.")
    new = ["Brand new translation."]
    # _on_translated 靠 _tr_inputs 知道这次翻的是哪几种语言。
    win._tr_inputs = (list(SEGMENTS), ["en"])
    win._on_translated(_FakeTranslation({"en": new}))
    assert win.table.item(0, COL_EN).text() == "Brand new translation."
    assert not _btn(win, 0).isEnabled(), "重新翻译后该行算未编辑"
    assert win.initial_cells[(0, COL_EN)] == "Brand new translation.", \
        "基线没有跟着重新翻译更新"


class _FakeTranslation:
    def __init__(self, texts):
        self.texts = texts
        self.elapsed = 1.0


def test_undo_survives_a_language_switch(win, monkeypatch):
    """切换语言要重新翻译按钮文案，但不能把用户的编辑弄丢或误判成没改过。"""
    _fill(win)
    win.table.item(0, COL_TEXT).setText("changed")
    monkeypatch.setattr(MainWindow, "_confirm_undo", lambda *a: True)
    i18n.set_language("ja")
    win.retranslate()
    assert _btn(win, 0).text() == i18n.t("row.undo")
    assert _btn(win, 0).isEnabled(), "切语言后按钮状态丢了"
    win._on_undo_clicked(0)
    assert win.table.item(0, COL_TEXT).text() == SEGMENTS[0]
    i18n.set_language("zh")


def test_undo_column_has_a_fixed_narrow_width(win):
    """撤销列跟着拉伸会让整张表右侧空一大块。"""
    _fill(win)
    mode = win.table.horizontalHeader().sectionResizeMode(COL_UNDO)
    from PySide6.QtWidgets import QHeaderView
    assert mode == QHeaderView.ResizeMode.Fixed
    assert win.table.columnWidth(COL_UNDO) <= 80, \
        f"撤销列太宽：{win.table.columnWidth(COL_UNDO)}px"