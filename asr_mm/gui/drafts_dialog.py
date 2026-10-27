"""草稿列表：查看、载入、删除上次转写的结果。

用户丢过编辑内容，所以光有缓存不够——得让人看得见、捞得回来。这个对话框
列出应用保存过的每一份草稿（时间、来源、片段数、有没有被手改过），可以
直接载入回表格。
"""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from .. import drafts as draft_store
from ..i18n import t


class DraftsDialog(QDialog):
    """Lists saved drafts. ``selected`` holds the one the user chose to load."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("drafts.title"))
        self.resize(760, 420)
        self.selected = None

        root = QVBoxLayout(self)

        hint = QLabel(t("drafts.hint"), self)
        hint.setWordWrap(True)
        root.addWidget(hint)

        self.table = QTableWidget(0, 4, self)
        self.table.setHorizontalHeaderLabels([t("drafts.col_time"),
                                              t("drafts.col_source"),
                                              t("drafts.col_rows"),
                                              t("drafts.col_state")])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        # 时间是定长格式，让它按内容定宽；来源列吃掉剩下的空间。
        # 不这么做的话，「2026-10-27 14:23」会被挤成「2026-10-27 …」。
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.itemDoubleClicked.connect(lambda *_: self._load())
        root.addWidget(self.table, 1)

        self.status = QLabel("", self)
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        row = QHBoxLayout()
        self.btn_load = QPushButton(t("drafts.load"), self)
        self.btn_load.clicked.connect(self._load)
        self.btn_delete = QPushButton(t("drafts.delete"), self)
        self.btn_delete.clicked.connect(self._delete)
        self.btn_folder = QPushButton(t("drafts.open_folder"), self)
        self.btn_folder.clicked.connect(self._open_folder)
        self.btn_close = QPushButton(t("drafts.close"), self)
        self.btn_close.clicked.connect(self.reject)
        for b in (self.btn_load, self.btn_delete, self.btn_folder):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(self.btn_close)
        root.addLayout(row)

        self._items: list[draft_store.Draft] = []
        # 老草稿别无限攒着，一次会话清一次就够。
        try:
            draft_store.prune()
        except OSError:
            pass
        self.reload()

    # ------------------------------------------------------------------ 列表
    def reload(self) -> None:
        self._items = draft_store.list_drafts()
        self.table.setRowCount(len(self._items))
        for row, d in enumerate(self._items):
            stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(d.updated_at))
            name = Path(d.source).name if d.source else t("drafts.no_source")
            cells = [
                stamp,
                name,
                str(len(d.segments)),
                t("drafts.state.edited") if d.edited else t("drafts.state.clean"),
            ]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if col == 0:
                    item.setData(0x0100, d.id)   # UserRole
                self.table.setItem(row, col, item)
        self._sync_buttons()
        if not self._items:
            self.status.setText(t("drafts.empty"))
        else:
            self.status.setText(t("drafts.count", count=len(self._items)))
            # 打开就选中最新的一条，「载入」立刻能点。
            self.table.setCurrentCell(0, 0)
            self._sync_buttons()

    def _current(self) -> draft_store.Draft | None:
        row = self.table.currentRow()
        if 0 <= row < len(self._items):
            return self._items[row]
        return None

    def _sync_buttons(self) -> None:
        has = self._current() is not None
        self.btn_load.setEnabled(has)
        self.btn_delete.setEnabled(has)

    # ------------------------------------------------------------------ 动作
    def _load(self) -> None:
        d = self._current()
        if d is None:
            return
        self.selected = d
        self.accept()

    def _delete(self) -> None:
        d = self._current()
        if d is None:
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(t("drafts.delete"))
        box.setText(t("drafts.delete_confirm", time=time.strftime(
            "%Y-%m-%d %H:%M", time.localtime(d.updated_at))))
        yes = box.addButton(t("drafts.delete"), QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(t("load.cancel"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is not yes:
            return
        draft_store.delete(d.id)
        self.reload()

    def _open_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(
            str(draft_store.drafts_dir())))
