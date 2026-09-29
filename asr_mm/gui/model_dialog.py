"""Dialog for fetching GGUF models on first use."""
from __future__ import annotations

import time

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout,
)

from .. import catalog, downloader


class _Fetch(QThread):
    progress = Signal(str, int, int)   # filename, done, total
    done = Signal(str, str)            # model_key, error("" when fine)
    log = Signal(str)

    def __init__(self, keys: list[str], parent=None):
        super().__init__(parent)
        self.keys = keys
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        for key in self.keys:
            if self._cancelled:
                break
            try:
                spec = catalog.resolve_model(key)
                missing = downloader.missing_files(spec)
                if not missing:
                    self.done.emit(key, "")
                    continue
                total = sum(f.size for f in missing)
                self.log.emit(f"{spec.label} — {downloader.human(total)}")
                state = {"t": 0.0}
                last_name = {"v": ""}

                def cb(name: str, d: int, t: int, key=key) -> None:
                    now = time.time()
                    if now - state["t"] < 0.1 and d < t:
                        return
                    state["t"] = now
                    if name != last_name["v"]:
                        last_name["v"] = name
                        self.log.emit(f"  {name}")
                    self.progress.emit(name, d, t or total)

                downloader.ensure_model(key, progress=cb)
                self.done.emit(key, "")
            except Exception as exc:
                self.done.emit(key, str(exc))


class ModelDownloadDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("下载识别模型")
        self.resize(560, 300)
        self.thread: _Fetch | None = None

        lay = QVBoxLayout(self)
        self.info = QLabel(
            "模型体积较大（Nano 约 911 MB，Paraformer 约 228 MB），只需下载一次，"
            "之后可离线使用。\n下载可随时中断，下次继续。")
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
        self.btn_all = QPushButton("下载全部")
        self.btn_all.clicked.connect(lambda: self.start(list(catalog.MODELS)))
        self.btn_nano = QPushButton("仅 Nano")
        self.btn_nano.clicked.connect(lambda: self.start(["nano"]))
        self.btn_fast = QPushButton("仅 Paraformer")
        self.btn_fast.clicked.connect(lambda: self.start(["paraformer"]))
        self.btn_close = QPushButton("关闭")
        self.btn_close.clicked.connect(self.close)
        for b in (self.btn_all, self.btn_nano, self.btn_fast):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(self.btn_close)
        lay.addLayout(row)

        self._refresh()

    def _refresh(self) -> None:
        rows = []
        for spec in catalog.MODELS.values():
            ready = not downloader.missing_files(spec)
            size = downloader.human(sum(f.size for f in spec.files))
            mark = "✓ 已就绪" if ready else "○ 未下载"
            rows.append(f"<b>{spec.key}</b> — {spec.label} · {size} · {mark}<br>"
                        f"<span style='color:#6b7280'>&nbsp;&nbsp;{spec.note}</span>")
        self.list.setText("<br>".join(rows))

    def start(self, keys: list[str]) -> None:
        if self.thread is not None:
            return
        self.bar.setValue(0)
        for b in (self.btn_all, self.btn_nano, self.btn_fast):
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
        self.bar.setFormat(f"{name}  %p%  ({downloader.human(done)}/{downloader.human(total)})")

    def _on_done(self, key: str, err: str) -> None:
        if err:
            self.info.setText(f"✗ {key} 下载失败：{err}")
        else:
            self._refresh()

    def closeEvent(self, ev) -> None:
        if self.thread is not None:
            self.thread.cancel()
            self.thread.wait(2000)
        super().closeEvent(ev)
