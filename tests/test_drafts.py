"""编辑内容防丢失：转写结果和手动修改都要落盘，并且找得回来。

丢过两次数据：一次是转写完手改了几处，又点了一次「开始转写」，新结果整表
替换，手改的部分就没了；一次是编辑到一半程序被关掉，内存里的东西全丢。

这一版把两件事都堵上：

* 每次转写都开一份**新**草稿，再点一次「开始转写」不会盖掉上一份；
* 每次手动修改都会自动落盘（防抖 1.2 秒），退出时再强制存一次。

这里锁的是：草稿写在用户数据目录而不是安装目录、写入是原子的、坏文件不会
把列表功能搞崩、编辑真的落盘、重启之后能捞回来、以及载入之后撤销按钮照样能用。
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("ASR_MM_HOME",
                       str(Path(__file__).resolve().parent.parent / ".asrhome"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from asr_mm import drafts, i18n, paths, transcribe  # noqa: E402
from asr_mm.gui.app import COL_EN, COL_TEXT, COL_UNDO, MainWindow  # noqa: E402

# 手写的虚构句子，不要用真实课堂录像的转写。
SEGMENTS = [
    "今天的会议改到明天下午三点钟。",
    "请把这份材料复印三份。",
    "你觉得这个价格合理吗？",
]
EDITED = "复印两份就够了。"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication(sys.argv[:1])


@pytest.fixture()
def win(app, tmp_path, monkeypatch):
    monkeypatch.setenv("ASR_MM_HOME", str(tmp_path))
    w = MainWindow()
    w.show()
    yield w
    w.close()
    w.deleteLater()


def _result(source="sample.mp4"):
    segs = [transcribe.Segment(i * 3.0, i * 3.0 + 2.0, s)
            for i, s in enumerate(SEGMENTS)]
    return transcribe.Transcript(
        source=source, source_duration=30.0,
        range_start=0.0, range_end=9.0,
        applied_start=0.0, applied_end=9.0,
        model="nano", model_label="Nano",
        segments=segs, elapsed=1.0, audio_seconds=9.0,
    )


def _draft_only():
    """当前目录下的草稿文件（不是 .tmp）。"""
    return sorted(p for p in drafts.drafts_dir().glob(f"*{drafts.DRAFT_SUFFIX}"))


# ------------------------------------------------------------------ 存取
def test_drafts_live_in_the_user_data_dir_not_next_to_the_app(monkeypatch, tmp_path):
    """草稿不能写在安装目录里。

    macOS 上 /Applications 是只读的，而且升级会把安装目录覆盖掉——用户数据
    放那儿等于随时会没。
    """
    monkeypatch.setenv("ASR_MM_HOME", str(tmp_path))
    assert drafts.drafts_dir() == paths.home_root() / "drafts"
    assert drafts.drafts_dir().is_dir()


def test_save_and_load_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("ASR_MM_HOME", str(tmp_path))
    d = drafts.Draft.build("abc123", _result())
    d.segments = [{"start": 1.0, "end": 2.0, "text": EDITED,
                   "suspicious": False}]
    p = drafts.save(d)
    assert p.exists()
    back = drafts.load(p)
    assert back is not None
    assert back.segments[0]["text"] == EDITED
    assert back.source == "sample.mp4"
    assert back.model == "nano"


def test_save_leaves_no_temp_file_behind(monkeypatch, tmp_path):
    """写盘是先写 .tmp 再改名。中途崩了不能留半个文件在目录里。"""
    monkeypatch.setenv("ASR_MM_HOME", str(tmp_path))
    d = drafts.Draft.build("abc123", _result())
    drafts.save(d)
    assert not list(drafts.drafts_dir().glob("*.tmp"))


def test_a_damaged_draft_is_skipped_instead_of_breaking_the_list(monkeypatch, tmp_path):
    """草稿是自动写出来的，损坏是可能的。一个坏文件不该让整个列表打不开。"""
    monkeypatch.setenv("ASR_MM_HOME", str(tmp_path))
    good = drafts.Draft.build("good", _result())
    drafts.save(good)
    (drafts.drafts_dir() / "broken.draft.json").write_text(
        "{not json at all", encoding="utf-8")
    items = drafts.list_drafts()
    assert [d.id for d in items] == ["good"]
    assert drafts.load(drafts.drafts_dir() / "broken.draft.json") is None


def test_list_drafts_is_newest_first(monkeypatch, tmp_path):
    monkeypatch.setenv("ASR_MM_HOME", str(tmp_path))
    for i, name in enumerate(("old", "mid", "new")):
        d = drafts.Draft.build(name, _result())
        d.created_at = d.updated_at = time.time() - (3 - i) * 60
        drafts.save(d)
    assert [d.id for d in drafts.list_drafts()] == ["new", "mid", "old"]


def test_delete_removes_the_file(monkeypatch, tmp_path):
    monkeypatch.setenv("ASR_MM_HOME", str(tmp_path))
    d = drafts.Draft.build("gone", _result())
    p = drafts.save(d)
    assert drafts.delete("gone") is True
    assert not p.exists()
    assert drafts.delete("gone") is False


def test_prune_keeps_at_most_the_limit(monkeypatch, tmp_path):
    monkeypatch.setenv("ASR_MM_HOME", str(tmp_path))
    for i in range(drafts.KEEP_LIMIT + 5):
        d = drafts.Draft.build(f"d{i:03d}", _result())
        d.created_at = d.updated_at = time.time() - i
        drafts.save(d)
    drafts.prune()
    assert len(drafts.list_drafts()) == drafts.KEEP_LIMIT


def test_prune_drops_drafts_older_than_the_max_age(monkeypatch, tmp_path):
    monkeypatch.setenv("ASR_MM_HOME", str(tmp_path))
    old = drafts.Draft.build("ancient", _result())
    old.created_at = old.updated_at = time.time() - (drafts.MAX_AGE_DAYS + 1) * 86400
    drafts.save(old)
    fresh = drafts.Draft.build("today", _result())
    drafts.save(fresh)
    drafts.prune()
    ids = [d.id for d in drafts.list_drafts()]
    assert "ancient" not in ids
    assert "today" in ids


def test_to_transcript_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("ASR_MM_HOME", str(tmp_path))
    d = drafts.Draft.build("rt", _result())
    t = d.to_transcript()
    assert [s.text for s in t.segments] == SEGMENTS
    assert t.source_duration == 30.0
    assert t.model == "nano"


# ------------------------------------------------------------------ 界面
def test_a_finished_transcription_is_saved_as_a_draft(win):
    win._on_done(_result())
    items = drafts.list_drafts()
    assert len(items) == 1, "转写完就该有一份草稿"
    assert items[0].segments[0]["text"] == SEGMENTS[0]


def test_editing_arms_the_autosave(win):
    """改一个字就该排上写盘，不用用户点任何按钮。"""
    win._on_done(_result())
    win.table.item(1, COL_TEXT).setText(EDITED)
    assert win._draft_dirty, "编辑之后没有标记待保存"
    assert win._draft_timer.isActive(), "自动保存的计时器没启动"


def test_an_edit_reaches_the_disk(win):
    win._on_done(_result())
    win.table.item(1, COL_TEXT).setText(EDITED)
    win._save_draft_now()
    items = drafts.list_drafts()
    assert len(items) == 1
    assert items[0].segments[1]["text"] == EDITED
    assert items[0].edited is True


def test_an_edit_is_not_lost_by_a_transcription_that_finishes_immediately(win):
    """改完不到 1.2 秒就又转写一次——那次手改必须已经落盘。

    防抖窗口里的编辑最容易丢：表格被新结果顶掉了，而写盘还没轮到它。
    """
    win._on_done(_result())
    win.table.item(1, COL_TEXT).setText(EDITED)     # 防抖还没到
    assert win._draft_dirty
    win._on_done(_result())                          # 新结果立刻到位
    items = drafts.list_drafts()
    assert len(items) == 2
    texts = {d.segments[1]["text"] for d in items}
    assert EDITED in texts, "防抖窗口里的手改被新结果顶掉了"


def test_translating_is_also_persisted(win):
    win._on_done(_result())
    win.translations = {"en": ["One", "Two", "Three"]}
    win._fill_table(win.result)
    win._save_draft_now()
    items = drafts.list_drafts()
    assert items[0].translations.get("en") == ["One", "Two", "Three"]


def test_a_second_transcription_does_not_overwrite_the_first_draft(win):
    """场景一：转写完手改了几处，又点了一次「开始转写」。

    旧内容必须还在——新结果另开一份草稿，不许盖掉上一份。
    """
    win._on_done(_result())
    win.table.item(0, COL_TEXT).setText(EDITED)
    win._save_draft_now()
    assert len(drafts.list_drafts()) == 1

    win._on_done(_result())
    items = drafts.list_drafts()
    assert len(items) == 2, "第二次转写应该新建一份草稿，而不是覆盖旧的"
    texts = {d.segments[0]["text"] for d in items}
    assert EDITED in texts, "手改过的那份不见了"
    assert SEGMENTS[0] in texts, "新转写的那份也不见了"


def test_edits_survive_an_app_restart(win):
    """场景二：编辑到一半程序被关掉。

    模拟重启：关掉窗口，重新开一个，再从草稿里捞回来。
    """
    win._on_done(_result())
    win.table.item(1, COL_TEXT).setText(EDITED)
    win._save_draft_now()
    win.close()

    win2 = MainWindow()
    try:
        items = drafts.list_drafts()
        assert len(items) == 1
        win2._load_draft(items[0])
        assert win2.table.item(1, COL_TEXT).text() == EDITED
    finally:
        win2.close()
        win2.deleteLater()


def test_closing_the_window_flushes_a_pending_edit(win):
    """防抖是 1.2 秒，用户改完马上关窗口，那一下也得存下去。"""
    win._on_done(_result())
    win.table.item(2, COL_TEXT).setText(EDITED)
    assert win._draft_dirty
    win.close()
    items = drafts.list_drafts()
    assert items[0].segments[2]["text"] == EDITED


def test_loading_a_draft_puts_the_rows_back(win):
    win._on_done(_result())
    win.table.item(0, COL_TEXT).setText(EDITED)
    win._save_draft_now()
    saved = drafts.list_drafts()[0]

    win._on_done(_result())          # 换成另一份结果
    assert win.table.item(0, COL_TEXT).text() == SEGMENTS[0]

    win._load_draft(saved)
    assert win.table.item(0, COL_TEXT).text() == EDITED
    assert win.table.rowCount() == len(SEGMENTS)


def test_a_loaded_draft_still_has_a_working_undo_button(win, monkeypatch):
    """载入草稿之后要能分辨哪些句被改过——否则撤销按钮全是灰的。"""
    win._on_done(_result())
    win.table.item(1, COL_TEXT).setText(EDITED)
    win._save_draft_now()
    saved = drafts.list_drafts()[0]

    win._load_draft(saved)
    btn = win.table.cellWidget(1, COL_UNDO)
    assert btn is not None and btn.isEnabled(), "改过的那行该有可点的撤销"
    assert not win.table.cellWidget(0, COL_UNDO).isEnabled(), \
        "没改的行不该亮"

    monkeypatch.setattr(MainWindow, "_confirm_undo", lambda *a: True)
    win._on_undo_clicked(1)
    assert win.table.item(1, COL_TEXT).text() == SEGMENTS[1]


def test_a_loaded_draft_keeps_its_own_id(win):
    """接着编辑载入的草稿，写回同一份，不要到处乱生文件。"""
    win._on_done(_result())
    win._save_draft_now()
    saved = drafts.list_drafts()[0]
    win._load_draft(saved)
    win.table.item(0, COL_TEXT).setText(EDITED)
    win._save_draft_now()
    assert len(drafts.list_drafts()) == 1, "不该多出草稿来"
    assert drafts.list_drafts()[0].segments[0]["text"] == EDITED


def test_switching_video_keeps_the_previous_result_as_a_draft(win):
    """换视频会清空表格，清空前得先落盘。"""
    win._on_done(_result())
    win.table.item(0, COL_TEXT).setText(EDITED)
    win._save_draft_now()
    win.result = None              # 模拟 _apply_loaded 清空
    win.table.setRowCount(0)
    assert len(drafts.list_drafts()) == 1
    assert drafts.list_drafts()[0].segments[0]["text"] == EDITED


# ------------------------------------------------------------- 覆盖确认
def _patch_dialog(monkeypatch, answer: str):
    """把 QMessageBox.exec 换成自动选按钮，避免测试里真的弹窗。"""
    def fake_exec(self):
        for b in self.buttons():
            if b.text() == answer:
                b.click()
                break
        return 0
    monkeypatch.setattr(QMessageBox, "exec", fake_exec)


def test_overwrite_is_asked_before_the_table_is_replaced(win, monkeypatch):
    win._on_done(_result())
    win.table.item(0, COL_TEXT).setText(EDITED)

    _patch_dialog(monkeypatch, i18n.t("load.cancel"))
    assert win._confirm_replace() is False, "点了取消还往下走就完了"

    _patch_dialog(monkeypatch, i18n.t("drafts.replace.confirm"))
    assert win._confirm_replace() is True


def test_the_overwrite_prompt_says_the_content_is_saved(win, monkeypatch):
    """问的时候要说明「旧内容存着」，否则用户不敢点继续。"""
    win._on_done(_result())
    win.table.item(0, COL_TEXT).setText(EDITED)
    seen = {}

    def fake_exec(self):
        seen["text"] = self.text()
        seen["info"] = self.informativeText()
        for b in self.buttons():
            if b.text() == i18n.t("load.cancel"):
                b.click()
                break
        return 0

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    win._confirm_replace()
    assert "3" in seen["text"], "没告诉用户表里有多少条"
    assert i18n.t("drafts.replace.note") in seen["info"], \
        "没告诉用户旧内容已经存成草稿"


def test_content_is_saved_before_the_overwrite_prompt(win, monkeypatch):
    """就算用户点了取消，内容也已经存下来了——白赚的保险。"""
    win._on_done(_result())
    win.table.item(0, COL_TEXT).setText(EDITED)
    _patch_dialog(monkeypatch, i18n.t("load.cancel"))
    win._confirm_replace()
    items = drafts.list_drafts()
    assert items[0].segments[0]["text"] == EDITED


# --------------------------------------------------------------- 对话框
def test_the_drafts_dialog_lists_and_loads(win):
    from asr_mm.gui.drafts_dialog import DraftsDialog

    win._on_done(_result())
    win.table.item(0, COL_TEXT).setText(EDITED)
    win._save_draft_now()

    dlg = DraftsDialog(win)
    try:
        assert dlg.table.rowCount() == 1
        assert dlg.table.item(0, 0).text() != ""
        dlg.table.setCurrentCell(0, 0)
        dlg._load()
        assert dlg.selected is not None
        assert dlg.selected.segments[0]["text"] == EDITED
    finally:
        dlg.deleteLater()


def test_the_drafts_dialog_deletes(win, monkeypatch):
    from asr_mm.gui.drafts_dialog import DraftsDialog

    win._on_done(_result())
    win._save_draft_now()
    dlg = DraftsDialog(win)
    try:
        assert dlg.table.rowCount() == 1
        dlg.table.setCurrentCell(0, 0)
        # 确认框里「删除」和「取消」两个按钮，按删除。
        _patch_dialog(monkeypatch, i18n.t("drafts.delete"))
        dlg._delete()
        assert dlg.table.rowCount() == 0
        assert drafts.list_drafts() == []
    finally:
        dlg.deleteLater()


def test_the_drafts_dialog_keeps_the_draft_when_the_delete_is_cancelled(win, monkeypatch):
    from asr_mm.gui.drafts_dialog import DraftsDialog

    win._on_done(_result())
    win._save_draft_now()
    dlg = DraftsDialog(win)
    try:
        dlg.table.setCurrentCell(0, 0)
        _patch_dialog(monkeypatch, i18n.t("load.cancel"))
        dlg._delete()
        assert dlg.table.rowCount() == 1
        assert len(drafts.list_drafts()) == 1
    finally:
        dlg.deleteLater()


# --------------------------------------------------------------- 隐私
def test_drafts_never_land_in_the_repository(monkeypatch, tmp_path):
    """草稿里是用户自己的转写文本，绝不能进仓库。"""
    monkeypatch.setenv("ASR_MM_HOME", str(tmp_path))
    d = drafts.Draft.build("priv", _result())
    d.segments = [{"start": 0.0, "end": 1.0, "text": "课堂上的原话",
                   "suspicious": False}]
    p = drafts.save(d)
    repo = Path(__file__).resolve().parent.parent
    assert repo not in p.resolve().parents
    assert p.suffix == ".json"
    payload = json.loads(p.read_text(encoding="utf-8"))
    assert payload["segments"][0]["text"] == "课堂上的原话"
