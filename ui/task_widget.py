"""Task widget — to-do list, tap to toggle. 440×440, text auto-fits width."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QVBoxLayout, QLabel

from ui.base_widget import BaseWidget, FitLabel, TRANS
from ui_backend.task_backend import get_manager


class _TaskRow(FitLabel):
    def __init__(self, task, on_toggle) -> None:
        super().__init__(max_pt=26)
        self._task      = task
        self._on_toggle = on_toggle
        color = "#555555" if task.done else "#dddddd"
        self.setStyleSheet(f"color: {color}; " + TRANS)
        self.setText(("✓ " if task.done else "○ ") + task.text)

    def mousePressEvent(self, _e) -> None:
        self._on_toggle(self._task)


class TaskWidget(BaseWidget):
    def __init__(self) -> None:
        super().__init__(fixed_size=(440, 440))
        self._rows: list[_TaskRow] = []

        self._layout = QVBoxLayout(self)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._layout.setContentsMargins(14, 14, 14, 14)
        self._layout.setSpacing(4)

        title = QLabel("TASKS")
        title.setFont(QFont("Arial", 11, QFont.Weight.Medium))
        title.setStyleSheet("color: #444444; letter-spacing: 3px; " + TRANS)
        self._layout.addWidget(title)

        poll = QTimer(self)
        poll.timeout.connect(self._refresh)
        poll.start(5_000)
        self._refresh()

    def _toggle(self, task) -> None:
        get_manager().complete(task.id, not task.done)
        self._refresh()

    def _refresh(self) -> None:
        for r in self._rows:
            r.setParent(None)
        self._rows.clear()
        for task in get_manager().list():
            row = _TaskRow(task, self._toggle)
            self._rows.append(row)
            self._layout.addWidget(row)
