"""Clock widget — day / time / date. Fixed 440×210, text scales to fit."""
from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QVBoxLayout, QLabel

from ui.base_widget import BaseWidget, TRANS
from ui import theme

CLOCK_HEIGHT = 210


class ClockWidget(BaseWidget):
    def __init__(self) -> None:
        super().__init__(fixed_size=(440, CLOCK_HEIGHT))

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(0)

        self._day = QLabel()
        self._day.setStyleSheet(f"color: {theme.dim}; letter-spacing: 4px; " + TRANS)
        self._day.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._day)

        self._time = QLabel()
        self._time.setStyleSheet(f"color: {theme.text}; " + TRANS)
        self._time.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._time)

        self._date = QLabel()
        self._date.setStyleSheet(f"color: {theme.mid}; " + TRANS)
        self._date.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._date)

        ticker = QTimer(self)
        ticker.timeout.connect(self._refresh)
        ticker.start(1000)
        self._refresh()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refit()

    def _refit(self) -> None:
        avail_w   = max(1, self.width() - 32)
        max_time_h = max(1, int((self.height() - 16) * 0.55))
        text = self._time.text() or "12:00"
        for pt in range(120, 8, -2):
            f  = QFont("Arial", pt, QFont.Weight.Thin)
            fm = QFontMetrics(f)
            if fm.horizontalAdvance(text) <= avail_w * 0.90 and fm.height() <= max_time_h:
                self._time.setFont(f)
                break
        f_day = QFont("Arial", max(8, pt // 5), QFont.Weight.Light)
        f_day.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 3)
        self._day.setFont(f_day)
        self._date.setFont(QFont("Arial", max(9, pt // 4), QFont.Weight.Light))

    def _refresh(self) -> None:
        now = datetime.now()
        self._day.setText(now.strftime("%A").upper())
        self._time.setText(now.strftime("%-I:%M"))
        self._date.setText(now.strftime("%-d %B %Y"))
        self._refit()
