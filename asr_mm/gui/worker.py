"""Background worker so recognition never blocks the UI."""
from __future__ import annotations

import traceback
from dataclasses import dataclass

from PySide6.QtCore import QThread, Signal

from .. import transcribe


@dataclass
class Job:
    video: str
    start: str
    end: str
    model: str
    preroll: float = 0.0
    drop_short: bool = False
    loudnorm: bool = False
    maxseg: int = 10_000
    threads: int | None = None


class TranscribeWorker(QThread):
    stage = Signal(str)                 # human-readable progress line
    finished_ok = Signal(object)        # transcribe.Transcript
    failed = Signal(str)

    def __init__(self, job: Job, parent=None):
        super().__init__(parent)
        self.job = job
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:  # executed on the worker thread
        try:
            self.stage.emit("正在抽取音频…")
            job = self.job
            result = transcribe.transcribe(
                job.video, start=job.start, end=job.end, model=job.model,
                vad_maxseg_ms=job.maxseg, threads=job.threads,
                preroll=job.preroll, loudnorm=job.loudnorm,
                drop_short=job.drop_short)
            if self._cancelled:
                self.failed.emit("已取消")
            else:
                self.stage.emit("完成")
                self.finished_ok.emit(result)
        except Exception as exc:
            detail = traceback.format_exc(limit=3)
            self.failed.emit(f"{exc}\n\n{detail}")
