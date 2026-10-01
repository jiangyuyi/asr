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


class TranslateWorker(QThread):
    """Load the models and translate on this thread.

    Model loading is a few hundred milliseconds per target and the run itself
    is seconds, but doing either on the GUI thread would freeze the window
    exactly the way the 1.2.0 load bug did.
    """

    progress = Signal(str, int, int)   # target, done, total
    finished_ok = Signal(object)       # translate.TranslationResult
    failed = Signal(str)

    def __init__(self, texts: list[str], targets: list[str], parent=None):
        super().__init__(parent)
        self.texts = list(texts)
        self.targets = list(targets)
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        from .. import translate as mt
        try:
            with mt.Translator(self.targets, progress=self.progress.emit) as tr:
                result = tr.translate(self.texts, should_cancel=self._is_cancelled)
            if self._cancelled:
                self.failed.emit(mt.t("err.mt_cancelled"))
            else:
                self.finished_ok.emit(result)
        except Exception as exc:
            detail = traceback.format_exc(limit=3)
            self.failed.emit(f"{exc}\n\n{detail}")

    def _is_cancelled(self) -> bool:
        return self._cancelled
