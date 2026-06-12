"""Timer widget — live countdown. 440×210, text auto-fits width."""
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QVBoxLayout, QLabel

from ui.base_widget import BaseWidget, FitLabel, TRANS
from ui_backend.timer_backend import get_manager


class TimerWidget(BaseWidget):
    _tick   = Signal(int, str, int)
    _finish = Signal(int, str)

    def __init__(self) -> None:
        super().__init__(fixed_size=(440, 210))
        self._rows: dict[int, FitLabel] = {}

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)

        title = QLabel("TIMERS")
        title.setFont(QFont("Arial", 11, QFont.Weight.Medium))
        title.setStyleSheet("color: #444444; letter-spacing: 3px; " + TRANS)
        layout.addWidget(title)
        self._layout = layout

        mgr = get_manager()
        mgr.on_tick   = lambda t: self._tick.emit(t.id, t.label, t.remaining)
        mgr.on_finish = lambda t: self._finish.emit(t.id, t.label)
        self._tick.connect(self._on_tick)
        self._finish.connect(self._on_finish)

    def _on_tick(self, tid: int, label: str, remaining: int) -> None:
        row = self._rows.get(tid)
        if row is None:
            row = FitLabel(max_pt=32)
            row.setStyleSheet("color: #dddddd; " + TRANS)
            self._rows[tid] = row
            self._layout.addWidget(row)
        m, s = divmod(remaining, 60)
        row.setText(f"{label}  {m:02d}:{s:02d}")

    def _on_finish(self, tid: int, label: str) -> None:
        row = self._rows.pop(tid, None)
        if row:
            row.setText(f"{label}  done")
            row.setStyleSheet("color: #006688; " + TRANS)
            QTimer.singleShot(5000, row.deleteLater)
