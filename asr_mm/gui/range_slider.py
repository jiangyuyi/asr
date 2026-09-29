"""A two-handle range slider for picking a start/end window on a timeline."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QStyle, QStyleOptionSlider, QWidget

HANDLE_W = 14


class RangeSlider(QWidget):
    """Start/end handles over a 0..duration track.

    Qt has no built-in range slider, and the value here is a *time window* on a
    video timeline, so this works in milliseconds and clamps the two handles to
    a minimum gap.
    """

    startMoved = Signal(float)
    endMoved = Signal(float)
    rangeChanged = Signal(float, float)

    def __init__(self, duration: float = 0.0, parent=None):
        super().__init__(parent)
        self._duration = max(0.0, duration)
        self._start = 0.0
        self._end = self._duration
        self._min_gap = 0.1
        self._active: int | None = None
        self._drag_offset = 0
        self.setMinimumHeight(28)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

    # ------------------------------------------------------------------ model
    def setDuration(self, seconds: float) -> None:
        self._duration = max(0.0, seconds)
        if self._end <= self._start or self._end > self._duration:
            self._end = self._duration
        self._start = min(self._start, max(0.0, self._duration - self._min_gap))
        self.update()

    def duration(self) -> float:
        return self._duration

    def range(self) -> tuple[float, float]:
        return self._start, self._end

    def setRange(self, start: float, end: float) -> None:
        if self._duration <= 0:
            return
        self._start = min(max(0.0, start), self._duration)
        self._end = min(max(self._start + self._min_gap, end), self._duration)
        self._end = max(self._end, self._start + self._min_gap)
        self.update()
        self.rangeChanged.emit(self._start, self._end)

    def setPlayhead(self, position: float) -> None:
        self._playhead = max(0.0, min(position, self._duration))
        self.update()

    # ----------------------------------------------------------------- coords
    def _track(self) -> QRect:
        return QRect(HANDLE_W, self.height() // 2 - 3,
                     max(1, self.width() - 2 * HANDLE_W), 6)

    def _x_for(self, t: float) -> int:
        tr = self._track()
        if self._duration <= 0:
            return tr.left()
        return tr.left() + int(round(tr.width() * (t / self._duration)))

    def _t_for(self, x: int) -> float:
        tr = self._track()
        if tr.width() <= 0 or self._duration <= 0:
            return 0.0
        ratio = (x - tr.left()) / tr.width()
        return max(0.0, min(self._duration, ratio * self._duration))

    def _handle_rect(self, x: int) -> QRect:
        return QRect(x - HANDLE_W // 2, self.height() // 2 - 9, HANDLE_W, 18)

    def _hit(self, pos: QPoint) -> int | None:
        for idx, t in ((0, self._start), (1, self._end)):
            if self._handle_rect(self._x_for(t)).adjusted(-4, -4, 4, 4).contains(pos):
                return idx
        return None

    # ----------------------------------------------------------------- events
    def mousePressEvent(self, ev) -> None:
        if self._duration <= 0 or ev.button() != Qt.LeftButton:
            return
        idx = self._hit(ev.position().toPoint())
        self._active = idx
        if idx is not None:
            self._drag_offset = self._x_for(self._start if idx == 0 else self._end) - ev.position().toPoint().x()
        self.update()

    def mouseMoveEvent(self, ev) -> None:
        if self._active is None or self._duration <= 0:
            return
        x = ev.position().toPoint().x() + self._drag_offset
        t = self._t_for(x)
        if self._active == 0:
            t = min(t, self._end - self._min_gap)
            self._start = max(0.0, t)
            self.startMoved.emit(self._start)
        else:
            t = max(t, self._start + self._min_gap)
            self._end = min(self._duration, t)
            self.endMoved.emit(self._end)
        self.update()
        self.rangeChanged.emit(self._start, self._end)

    def mouseReleaseEvent(self, ev) -> None:
        self._active = None
        self._drag_offset = 0
        self.update()

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        tr = self._track()
        x0, x1 = self._x_for(self._start), self._x_for(self._end)

        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#d0d0d0"))
        p.drawRoundedRect(tr, 3, 3)
        p.setBrush(QColor("#3b82f6"))
        p.drawRoundedRect(QRect(x0, tr.top(), max(2, x1 - x0), tr.height()), 3, 3)

        ph = getattr(self, "_playhead", 0.0)
        if self._duration > 0:
            xp = self._x_for(ph)
            p.setPen(QPen(QColor("#ef4444"), 2))
            p.drawLine(xp, tr.top() - 6, xp, tr.bottom() + 6)

        for x, active in ((x0, self._active == 0), (x1, self._active == 1)):
            p.setPen(QPen(QColor("#1f2937"), 1))
            p.setBrush(QColor("#ffffff") if not active else QColor("#3b82f6"))
            p.drawRoundedRect(self._handle_rect(x), 4, 4)
        p.end()
