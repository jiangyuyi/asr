"""Dialog for fetching the CTranslate2 translation models on first use."""
from __future__ import annotations

import time

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout,
)

from .. import catalog, downloader
from ..i18n import t

TARGETS = catalog.mt_targets()


class _Fetch(QThread):
    progress = Signal(str, int, int)   # filename, done, total
    done = Signal(str, str)            # target, error("" when fine)
    log = Signal(str)

    def __init__(self, keys: list[str], parent=None):
        super().__init__(parent)
        self.keys = list(keys)
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        for key in self.keys:
            if self._cancelled:
                break
            try:
                spec = catalog.MT_MODELS[key]
                missing = downloader.mt_missing_files(spec)
                if not missing:
                    self.done.emit(key, "")
                    continue
                total = sum(f.size for f in missing)
                self.log.emit(f"{t('mt.' + key)} — {downloader.human(total)}")
                state = {"t": 0.0, "name": ""}

                def cb(name: str, d: int, tot: int, key=key) -> None:
                    now = time.time()
                    if now - state["t"] < 0.1 and d < tot:
                        return
                    state["t"] = now
                    if name != state["name"]:
                        state["name"] = name
                        self.log.emit(f"  {name}")
                    self.progress.emit(name, d, tot or total)

                downloader.ensure_mt_model(key, progress=cb)
                self.done.emit(key, "")
            except Exception as exc:
                self.done.emit(key, str(exc))


class MtDownloadDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.resize(560, 300)
        self.thread: _Fetch | None = None

        lay = QVBoxLayout(self)
        self.info = QLabel()
        self.info.setWordWrap(True)
        lay.addWidget(self.info)

        self.list = QLabel()
        self.list.setWordWrap(True)
        lay.addWidget(self.list)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        lay.addWidget(self.bar)

        row = QHBoxLayout()
        self._row = row
        self._net_btn_shown = False
        self.btn_all = QPushButton()
        self.btn_all.clicked.connect(lambda: self.start(list(TARGETS)))
        # One button per available target; the set is small and keeps growing
        # one language at a time.
        self._target_btns = []
        for code in TARGETS:
            b = QPushButton()
            b.clicked.connect(lambda _=False, c=code: self.start([c]))
            self._target_btns.append(b)
        self.btn_close = QPushButton()
        self.btn_close.clicked.connect(self.close)
        row.addWidget(self.btn_all)
        for b in self._target_btns:
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(self.btn_close)
        lay.addLayout(row)

        self.retranslate()
        self._refresh()

    def retranslate(self) -> None:
        self.setWindowTitle(t("mt.title"))
        # Plain comma: a CJK ideographic separator reads wrong in the English
        # and Japanese strings, and this line is built once per language switch.
        summary = ", ".join(f"{t('mt.' + c)} {self._size(c)}" for c in TARGETS)
        self.info.setText(t("mt.intro", models=summary))
        self.btn_all.setText(t("mt.all"))
        for code, b in zip(TARGETS, self._target_btns):
            b.setText(t(f"mt.only_{code}"))
        self.btn_close.setText(t("mt.close"))

    @staticmethod
    def _size(code: str) -> str:
        spec = catalog.MT_MODELS.get(code)
        return downloader.human(spec.size()) if spec else "—"

    def _refresh(self) -> None:
        rows = []
        for code in TARGETS:
            ready = catalog.mt_model_ready(code)
            mark = (t("models.state_ready") if ready
                    else t("models.state_missing"))
            rows.append(
                f"<b>{t('mt.' + code)}</b> — {self._size(code)} · {mark}<br>"
                f"<span style='color:#6b7280'>&nbsp;&nbsp;"
                f"{t('mt.' + code + '.note')}</span>")
        self.list.setText("<br>".join(rows))

    def start(self, keys: list[str]) -> None:
        if self.thread is not None:
            return
        self.bar.setValue(0)
        for b in [self.btn_all, *self._target_btns]:
            b.setEnabled(False)
        self.thread = _Fetch(keys, self)
        self.thread.progress.connect(self._on_progress)
        self.thread.done.connect(self._on_done)
        self.thread.log.connect(self.info.setText)
        self.thread.start()

    def _on_progress(self, name: str, done: int, total: int) -> None:
        if not total:
            return
        self.bar.setValue(int(done / total * 100))
        self.bar.setFormat(
            f"{name}  %p%  ({downloader.human(done)}/{downloader.human(total)})")

    def _on_done(self, key: str, err: str) -> None:
        if err:
            detail = downloader.explain(Exception(err))
            self.info.setText(t("mt.failed", key=t("mt." + key), error=detail))
            self.bar.setValue(0)
            if not self._net_btn_shown:
                self._net_btn_shown = True
                self.btn_net = QPushButton(t("net.title"))
                self.btn_net.clicked.connect(self._open_net_settings)
                self._row.addWidget(self.btn_net)
        else:
            self._refresh()

    def _open_net_settings(self) -> None:
        from .net_dialog import NetworkSettingsDialog
        dlg = NetworkSettingsDialog(self)
        dlg.exec()
        self._refresh()

    def changeEvent(self, ev) -> None:
        if ev.type() == ev.Type.LanguageChange:
            self.retranslate()
            self._refresh()
        super().changeEvent(ev)

    def closeEvent(self, ev) -> None:
        if self.thread is not None:
            self.thread.cancel()
            self.thread.wait(2000)
        super().closeEvent(ev)
