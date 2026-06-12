"""Alarm widget — upcoming alarms. 440×210, text auto-fits width."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QVBoxLayout, QLabel

from ui.base_widget import BaseWidget, FitLabel, TRANS
from ui_backend.alarm_backend import get_manager


class AlarmWidget(BaseWidget):
    def __init__(self) -> None:
        super().__init__(fixed_size=(440, 210))
        self._rows: list[FitLabel] = []

        self._layout = QVBoxLayout(self)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._layout.setContentsMargins(14, 12, 14, 12)
        self._layout.setSpacing(4)

        title = QLabel("ALARMS")
        title.setFont(QFont("Arial", 11, QFont.Weight.Medium))
        title.setStyleSheet("color: #444444; letter-spacing: 3px; " + TRANS)
        self._layout.addWidget(title)

        poll = QTimer(self)
        poll.timeout.connect(self._refresh)
        poll.start(10_000)
        self._refresh()

    def _refresh(self) -> None:
        for r in self._rows:
            r.setParent(None)
        self._rows.clear()

        alarms = sorted(get_manager().active(), key=lambda a: a.target)
        for a in alarms:
            lbl = FitLabel(max_pt=28)
            lbl.setStyleSheet("color: #dddddd; " + TRANS)
            t = a.target.strftime("%I:%M %p").lstrip("0")
            suffix = "  ↻" if a.repeat_daily else ""
            lbl.setText(f"{t}  {a.label}{suffix}")
            self._rows.append(lbl)
            self._layout.addWidget(lbl)
