"""Background video loading, so the window never blocks.

Loading a file used to do ffprobe and a first-frame grab on the GUI thread.
On a slow disk, a network share, or a large file that is seconds of silence
with no repaint — indistinguishable from a crash.

This worker does it off-thread and reports two phases:

    0.00 – 0.15   probing the container for duration and streams
    0.15 – 1.00   decoding the poster frame, with real ffmpeg progress

The poster is worth doing anyway: it is what the player fallback needs, and it
gives immediate visual confirmation that the file really opened.
"""
from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QProgressDialog

from .. import media

PROBE_SHARE = 0.15


class LoadProgressDialog(QProgressDialog):
    """QProgressDialog that actually reports cancellation.

    ``QProgressDialog.cancel()`` hides the dialog but does **not** emit
    ``canceled()`` in Qt 6 / PySide6 — verified against PySide6 6.11. Connecting
    to ``canceled`` therefore never fires, and the Cancel button silently does
    nothing. Overriding ``cancel`` catches both the button and any programmatic
    call, which is what a keyboard Escape or a window close turns into.
    """

    cancelRequested = Signal()

    def cancel(self) -> None:  # noqa: D102 - Qt override
        self.cancelRequested.emit()
        super().cancel()

    def closeEvent(self, ev) -> None:  # noqa: D102 - Qt override
        self.cancelRequested.emit()
        super().closeEvent(ev)


@dataclass
class LoadedVideo:
    path: Path
    info: media.MediaInfo
    poster: Path | None = None
    poster_pixmap_needs_load: bool = True


class LoadWorker(QThread):
    """Probe + poster, off the GUI thread."""

    progress = Signal(float, str)      # 0.0-1.0, status key
    done = Signal(object)              # LoadedVideo
    failed = Signal(str)               # already-localised message
    poster_ready = Signal(str)         # jpeg path, as soon as it exists

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.path = Path(path)
        self._cancelled = False
        self._proc: subprocess.Popen | None = None
        self._procs: list = []

    def cancel(self) -> None:
        self._cancelled = True
        for proc in (self._procs if isinstance(self._procs, list) else []):
            if proc.poll() is None:
                try:
                    proc.kill()
                except OSError:
                    pass
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                pass

    def run(self) -> None:  # worker thread
        try:
            self.progress.emit(0.02, "load.probing")
            if self._cancelled:
                return
            # Hand the probe process to cancel() so a stuck ffmpeg on a slow
            # share can still be interrupted, and so closing the window never
            # leaves this thread running past the app's shutdown.
            self._procs = []
            try:
                info = media.probe(self.path, proc_box=self._procs)
            finally:
                self._procs = []
            if self._cancelled:
                return

            poster: Path | None = None
            with tempfile.TemporaryDirectory(prefix="asr-mm-poster-") as td:
                jpg = Path(td) / "poster.jpg"
                # Seek a little way in: frame 0 is often black.
                at = min(1.0, max(0.0, info.duration / 20.0))

                def on_micros(micros: int) -> None:
                    if self._cancelled:
                        return
                    # ffmpeg's out_time_* is microseconds.
                    total_us = max(1.0, (at + 1.0) * 1_000_000)
                    frac = PROBE_SHARE + (1.0 - PROBE_SHARE) * min(
                        1.0, micros / total_us)
                    self.progress.emit(frac, "load.decoding")

                self.progress.emit(PROBE_SHARE, "load.decoding")
                try:
                    poster = media.thumbnail(self.path, jpg, at=at,
                                             on_progress=on_micros,
                                             proc=self._proc)
                except Exception:
                    poster = None
                if poster is not None:
                    # Copy out of the temp dir before it disappears.
                    keep = Path(tempfile.gettempdir()) / (
                        f"asr-mm-poster-{abs(hash(str(self.path)))}.jpg")
                    try:
                        keep.write_bytes(poster.read_bytes())
                        poster = keep
                        self.poster_ready.emit(str(keep))
                    except OSError:
                        poster = None

            if self._cancelled:
                return
            self.progress.emit(1.0, "load.done")
            self.done.emit(LoadedVideo(path=self.path, info=info, poster=poster))
        except media.MediaError as exc:
            if not self._cancelled:
                self.failed.emit(str(exc))
        except Exception as exc:  # pragma: no cover
            if not self._cancelled:
                self.failed.emit(str(exc))
