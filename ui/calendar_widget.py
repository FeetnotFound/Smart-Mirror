"""Calendar widget — horizontal 7-day columns, block-style events."""
from datetime import date, datetime, timedelta

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QFrame, QSizePolicy, QWidget,
)

from ui.base_widget import BaseWidget, TRANS
from ui import theme
from ui_backend.calendar_backend import get_backend, Event

def _cal_rgba(name: str, alpha: int) -> str:
    from ui_backend.calendar_backend import get_backend
    h = get_backend().get_calendar_color(name)
    r, g, b = int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)
    return f"rgba({r},{g},{b},{alpha})"

def _time_str(iso: str) -> str:
    """'all day' for date-only or midnight; otherwise '8:30' style."""
    if "T" not in iso:
        return "all day"
    dt = datetime.fromisoformat(iso)
    if dt.hour == 0 and dt.minute == 0 and dt.second == 0:
        return "all day"
    return dt.strftime("%-I:%M")

def _event_date(iso: str) -> date:
    return date.fromisoformat(iso[:10])


class _EventEntry(QWidget):
    def __init__(self, event: Event) -> None:
        super().__init__()
        bg  = _cal_rgba(event.calendar_name, 45)
        bdr = _cal_rgba(event.calendar_name, 110)
        tc  = _cal_rgba(event.calendar_name, 210)

        self.setObjectName("evtblock")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"#evtblock {{ background: {bg}; border: 1px solid {bdr};"
            " border-radius: 4px; }")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 3, 6, 3)
        layout.setSpacing(1)

        time_lbl = QLabel(_time_str(event.start_iso))
        time_lbl.setFont(QFont("Arial", 9, QFont.Weight.Light))
        time_lbl.setStyleSheet(f"color: {tc}; " + TRANS)
        layout.addWidget(time_lbl)

        title_lbl = QLabel(event.title)
        title_lbl.setFont(QFont("Arial", 11, QFont.Weight.Normal))
        title_lbl.setStyleSheet(f"color: {theme.text}; " + TRANS)
        title_lbl.setWordWrap(True)
        layout.addWidget(title_lbl)

        if event.calendar_name:
            cal_lbl = QLabel(event.calendar_name.upper())
            cal_lbl.setFont(QFont("Arial", 8, QFont.Weight.Light))
            cal_lbl.setStyleSheet(f"color: {tc}; letter-spacing: 1px; " + TRANS)
            layout.addWidget(cal_lbl)


class _DayColumn(QWidget):
    def __init__(self, d: date, events: list) -> None:
        super().__init__()
        self.setStyleSheet(TRANS)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(3)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        today    = date.today()
        tomorrow = today + timedelta(days=1)
        label    = ("TODAY" if d == today else
                    "TMRW"  if d == tomorrow else
                    d.strftime("%a %-d").upper())
        color    = "#aaaaaa" if d == today else "#555555"

        hdr = QLabel(label)
        hdr.setFont(QFont("Arial", 9, QFont.Weight.Medium))
        hdr.setStyleSheet(f"color: {color}; letter-spacing: 1px; " + TRANS)
        layout.addWidget(hdr)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background: #1e1e1e; border: none;")
        sep.setFixedHeight(1)
        layout.addWidget(sep)

        for evt in sorted(events, key=lambda e: e.start_iso):
            layout.addWidget(_EventEntry(evt))

        layout.addStretch()


class CalendarWidget(BaseWidget):
    def __init__(self, days: int = 7) -> None:
        super().__init__(expanding=True)
        self._days = days

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(6)

        hdr = QLabel("CALENDAR")
        hdr.setFont(QFont("Arial", 11, QFont.Weight.Medium))
        hdr.setStyleSheet(f"color: {theme.dim}; letter-spacing: 3px; " + TRANS)
        outer.addWidget(hdr)

        self._cols_w = QWidget()
        self._cols_w.setStyleSheet(TRANS)
        self._cols_layout = QHBoxLayout(self._cols_w)
        self._cols_layout.setContentsMargins(0, 0, 0, 0)
        self._cols_layout.setSpacing(0)
        outer.addWidget(self._cols_w, 1)

        poll = QTimer(self)
        poll.timeout.connect(self._refresh)
        poll.start(300_000)
        self._refresh()

    def _clear(self) -> None:
        while self._cols_layout.count():
            item = self._cols_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _refresh(self) -> None:
        self._clear()
        events = get_backend().upcoming(14)
        today  = date.today()

        by_day: dict[date, list] = {}
        for e in events:
            by_day.setdefault(_event_date(e.start_iso), []).append(e)

        for i in range(self._days):
            d = today + timedelta(days=i)
            if i > 0:
                vsep = QFrame()
                vsep.setFrameShape(QFrame.Shape.VLine)
                vsep.setStyleSheet("background: #1a1a1a; border: none;")
                vsep.setFixedWidth(1)
                self._cols_layout.addWidget(vsep)
            self._cols_layout.addWidget(_DayColumn(d, by_day.get(d, [])))
