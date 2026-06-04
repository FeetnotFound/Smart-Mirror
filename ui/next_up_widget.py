"""Next Up widget — single next calendar event. 440×210."""
from datetime import date, datetime, timedelta

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QFrame

from ui.base_widget import BaseWidget, FitLabel, TRANS
from ui import theme
from ui_backend.calendar_backend import get_backend

def _cal_rgba(name: str, alpha: int) -> str:
    from ui_backend.calendar_backend import get_backend
    h = get_backend().get_calendar_color(name)
    r, g, b = int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)
    return f"rgba({r},{g},{b},{alpha})"

def _time_str(iso: str) -> str:
    """Return display time; 'all day' for date-only or midnight datetimes."""
    if "T" not in iso:
        return "all day"
    dt = datetime.fromisoformat(iso)
    if dt.hour == 0 and dt.minute == 0 and dt.second == 0:
        return "all day"
    return dt.strftime("%-I:%M %p")

def _day_label(iso: str) -> str:
    d = date.fromisoformat(iso[:10])
    today = date.today()
    if d == today:
        return "Today"
    if d == today + timedelta(days=1):
        return "Tomorrow"
    return d.strftime("%A %-d %b")


class NextUpWidget(BaseWidget):
    def __init__(self) -> None:
        super().__init__(fixed_size=(440, 210))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        hdr = QLabel("NEXT UP")
        hdr.setFont(QFont("Arial", 11, QFont.Weight.Medium))
        hdr.setStyleSheet("color: #444444; letter-spacing: 3px; " + TRANS)
        layout.addWidget(hdr)

        from PySide6.QtCore import Qt as _Qt
        from PySide6.QtWidgets import QWidget as _QW
        self._block = _QW()
        self._block.setObjectName("nextblock")
        self._block.setAttribute(_Qt.WidgetAttribute.WA_StyledBackground, True)
        layout.addWidget(self._block, 1)

        bl = QVBoxLayout(self._block)
        bl.setContentsMargins(10, 8, 10, 8)
        bl.setSpacing(4)

        self._time_lbl  = QLabel()
        self._time_lbl.setFont(QFont("Arial", 11, QFont.Weight.Light))
        self._time_lbl.setStyleSheet(f"color: {theme.dim}; " + TRANS)
        bl.addWidget(self._time_lbl)

        self._title_lbl = FitLabel(max_pt=30)
        self._title_lbl.setStyleSheet(f"color: {theme.text}; " + TRANS)
        bl.addWidget(self._title_lbl)

        self._day_lbl = QLabel()
        self._day_lbl.setFont(QFont("Arial", 12, QFont.Weight.Light))
        self._day_lbl.setStyleSheet(f"color: {theme.mid}; " + TRANS)
        bl.addWidget(self._day_lbl)

        self._cal_lbl = QLabel()
        self._cal_lbl.setFont(QFont("Arial", 9, QFont.Weight.Light))
        self._cal_lbl.setStyleSheet(f"color: {theme.dim}; letter-spacing: 1px; " + TRANS)
        bl.addWidget(self._cal_lbl)
        bl.addStretch()

        poll = QTimer(self)
        poll.timeout.connect(self._refresh)
        poll.start(30_000)
        self._refresh()

    def _refresh(self) -> None:
        events = get_backend().upcoming(14)
        if not events:
            self._block.setStyleSheet(
                "#nextblock { background: rgba(40,40,40,80);"
                " border: 1px solid #222; border-radius: 5px; }")
            self._time_lbl.setText("")
            self._title_lbl.setText("nothing coming up")
            self._title_lbl.setStyleSheet(f"color: {theme.dim}; " + TRANS)
            self._day_lbl.setText("")
            self._cal_lbl.setText("")
            return

        evt = events[0]
        bg  = _cal_rgba(evt.calendar_name, 45)
        bdr = _cal_rgba(evt.calendar_name, 110)
        tc  = _cal_rgba(evt.calendar_name, 220)

        self._block.setStyleSheet(
            f"#nextblock {{ background: {bg}; border: 1px solid {bdr};"
            " border-radius: 5px; }")
        self._time_lbl.setStyleSheet(f"color: {tc}; " + TRANS)
        self._time_lbl.setText(_time_str(evt.start_iso))
        self._title_lbl.setStyleSheet(f"color: {theme.text}; " + TRANS)
        self._title_lbl.setText(evt.title)
        self._day_lbl.setText(_day_label(evt.start_iso))
        self._cal_lbl.setText(evt.calendar_name.upper() if evt.calendar_name else "")
