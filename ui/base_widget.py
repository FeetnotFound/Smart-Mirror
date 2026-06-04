"""Shared base for all mirror panel widgets.

Centralises the boilerplate that every panel needs:
  - dark panel stylesheet  (background, border, border-radius)
  - WA_StyledBackground   (required for QWidget subclasses to paint bg)
  - setRetainSizeWhenHidden  (layout stays stable when a widget is hidden)
  - fixed-size OR expanding size policy, caller's choice

Usage
-----
Fixed-size panel (440 × 210):
    class TimerWidget(BaseWidget):
        def __init__(self) -> None:
            super().__init__(fixed_size=(440, 210))

Expanding panel (fills its grid cell):
    class CalendarWidget(BaseWidget):
        def __init__(self) -> None:
            super().__init__(expanding=True)

The module also exports:
  TRANS      — stylesheet string that resets label backgrounds / italic
  FitLabel   — QLabel subclass whose font auto-scales to fill available width
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget

PANEL_SS = (
    "#panel { background-color: #0a0a0a;"
    " border: 1px solid #222222; border-radius: 6px; }"
)
TRANS = "background: transparent; font-style: normal;"


class FitLabel(QLabel):
    """Single-line label whose font grows to fill available width."""

    def __init__(self,
                 max_pt: int = 28,
                 weight: QFont.Weight = QFont.Weight.Normal) -> None:
        super().__init__()
        self._max    = max_pt
        self._weight = weight

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        self._fit()

    def setText(self, t: str) -> None:
        super().setText(t)
        self._fit()

    def _fit(self) -> None:
        txt = self.text()
        w   = self.width()
        if not txt or w <= 4:
            return
        for pt in range(self._max, 7, -1):
            f = QFont("Arial", pt, self._weight)
            if QFontMetrics(f).horizontalAdvance(txt) <= w - 4:
                self.setFont(f)
                return


class BaseWidget(QWidget):
    """Base class for all mirror panel widgets."""

    def __init__(self,
                 fixed_size: tuple | None = None,
                 expanding: bool = False) -> None:
        super().__init__()
        self.setObjectName("panel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(PANEL_SS)

        if fixed_size:
            self.setFixedSize(*fixed_size)
            sp = self.sizePolicy()
        elif expanding:
            sp = QSizePolicy(QSizePolicy.Policy.Expanding,
                             QSizePolicy.Policy.Expanding)
        else:
            sp = self.sizePolicy()

        sp.setRetainSizeWhenHidden(True)
        self.setSizePolicy(sp)
