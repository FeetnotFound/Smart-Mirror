import sys
import dotenv
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QGridLayout, QVBoxLayout, QHBoxLayout,
    QStackedWidget,
)
from PySide6.QtCore import Qt, QThread, QTimer

from ai.llm import preload_models
from ai.stt import run_stt
from ui.terminal import Terminal, LogStream
from ui.clock_widget import ClockWidget
from ui.calendar_widget import CalendarWidget
from ui.task_widget import TaskWidget
from ui.timer_widget import TimerWidget
from ui.alarm_widget import AlarmWidget
from ui.system_info_widget import SystemInfoWidget
from ui.next_up_widget import NextUpWidget
from ui.music_widget import MusicWidget
from ui_backend.ui_control_backend import ui_bus


dotenv.load_dotenv("variables.env")

# ── STT worker thread ─────────────────────────────────────────────────────────

class STTThread(QThread):
    """Runs run_stt() on a background thread.

    The UI is driven entirely by captured stdout (see terminal.LogStream), so
    every [Ear]/[Voice]/[System]/[Router]/[AI]/[Executer] line printed by the
    pipeline lands in the on-screen terminal — no per-event signals needed.
    """

    def run(self) -> None:
        run_stt()


# ── Mirror window ─────────────────────────────────────────────────────────────

class MirrorWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Mirror")
        self.setStyleSheet("background-color: #000000;")

        root = QWidget()
        self.setCentralWidget(root)

        # 2×2 grid. The terminal is pinned to the top-left cell; the stretched
        # row/column leave the other three corners free for future modules
        # (clock, weather, calendar, …). Drop new widgets into (0,1)/(1,0)/(1,1).
        grid = QGridLayout(root)
        grid.setContentsMargins(28, 28, 28, 28)
        grid.setSpacing(28)

        # ── top-left: terminal log ────────────────────────────────────────
        self.terminal = Terminal(line_spacing=1.8)
        grid.addWidget(self.terminal, 0, 0,
                        Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        # ── top-right: calendar — fills all remaining space in row 0 ─────
        # No alignment flags: grid stretches the widget to fill the cell.
        # Row 0 height is fixed by the terminal's setFixedSize(440); column 1
        # has setColumnStretch(1,1) so the calendar spans the full right half.
        self.calendar_widget = CalendarWidget(days=7)
        grid.addWidget(self.calendar_widget, 0, 1)

        # ── accent row — spans both columns, absorbs the vertical gap ───────
        # Row 1 gets all the stretch so the gap becomes intentional space
        # with a hairline divider and the mirror name centred in it.
        from PySide6.QtWidgets import QFrame as _QFrame
        accent = QWidget()
        accent.setStyleSheet("background: transparent;")
        _al = QHBoxLayout(accent)
        _al.setContentsMargins(0, 0, 0, 0)
        _al.setSpacing(20)

        _line_l = _QFrame(); _line_l.setFrameShape(_QFrame.Shape.HLine)
        _line_l.setStyleSheet("background: #2e2e2e; border: none; max-height: 1px;")
        _line_r = _QFrame(); _line_r.setFrameShape(_QFrame.Shape.HLine)
        _line_r.setStyleSheet("background: #2e2e2e; border: none; max-height: 1px;")

        from PySide6.QtWidgets import QLabel as _QL
        from PySide6.QtGui import QFont as _QF
        _name = _QL("MILLER")
        _name.setFont(_QF("Arial", 11, _QF.Weight.Light))
        _name.setStyleSheet(
            "color: #d0d0d0; letter-spacing: 8px;"
            "background: transparent; font-style: normal;")

        _al.addWidget(_line_l, 1)
        _al.addWidget(_name)
        _al.addWidget(_line_r, 1)
        grid.addWidget(accent, 1, 0, 1, 2)   # span both columns

        # ── bottom-left: task list ────────────────────────────────────────
        self.task_widget = TaskWidget()
        grid.addWidget(self.task_widget, 2, 0,
                        Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft)

        # ── bottom-right: clock (fills space) + timer/alarm stacked ─────
        right_row = QWidget()
        right_layout = QHBoxLayout(right_row)
        right_layout.setAlignment(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)
        right_layout.setSpacing(28)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # Three symmetric 440×440 stacks:
        # VBox[Clock, NextUp] | VBox[Timer, Alarm] | SysInfo
        # 440 + 28 + 440 + 28 + 440 = 1376px (fits in column 1)

        def _vstack(*widgets):
            w = QWidget()
            w.setStyleSheet("background: transparent;")
            v = QVBoxLayout(w)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(20)
            for ww in widgets:
                v.addWidget(ww)
            return w

        self.clock_widget   = ClockWidget()
        self.next_up_widget = NextUpWidget()
        right_layout.addWidget(_vstack(self.clock_widget, self.next_up_widget))

        self.timer_widget = TimerWidget()
        self.alarm_widget = AlarmWidget()
        right_layout.addWidget(_vstack(self.timer_widget, self.alarm_widget))

        # System info and Music share the right-most 440×440 slot.
        # Music takes over when AirPlay is active.
        self.system_widget = SystemInfoWidget()
        self.music_widget  = MusicWidget()

        self._sys_stack = QStackedWidget()
        self._sys_stack.setFixedSize(440, 440)
        sp = self._sys_stack.sizePolicy()
        sp.setRetainSizeWhenHidden(True)
        self._sys_stack.setSizePolicy(sp)
        self._sys_stack.addWidget(self.system_widget)  # index 0
        self._sys_stack.addWidget(self.music_widget)   # index 1
        right_layout.addWidget(self._sys_stack)

        _music_poll = QTimer(self)
        _music_poll.timeout.connect(self._sync_music_slot)
        _music_poll.start(3_000)

        grid.addWidget(right_row, 2, 1,
                        Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)

        grid.setRowStretch(1, 1)   # accent row absorbs all extra vertical space
        grid.setColumnStretch(1, 1)

        self._widgets: dict[str, QWidget] = {
            "terminal": self.terminal,
            "calendar": self.calendar_widget,
            "tasks":    self.task_widget,
            "clock":    self.clock_widget,
            "timer":    self.timer_widget,
            "alarm":    self.alarm_widget,
            "system":   self.system_widget,
            "music":    self.music_widget,
            "next_up":  self.next_up_widget,
        }

        self._stt = None

    def _sync_music_slot(self) -> None:
        """Switch the system-info slot to Music when AirPlay is active."""
        self._sys_stack.setCurrentIndex(1 if self.music_widget.is_playing else 0)

    # ── Logging ───────────────────────────────────────────────────────────

    def append_log(self, line: str) -> None:
        self.terminal.append_line(line)

    # ── UI control (called via Qt signal from worker thread) ───────────────

    def handle_ui_command(self, action: str, module: str,
                          location: str, size: str) -> None:
        widget = self._widgets.get(module)
        if widget is None:
            print(f"[UI] unknown module: {module!r}")
            return
        if action == "show":
            widget.show()
        elif action == "hide":
            widget.hide()
        print(f"[UI] {action} {module}"
              + (f" at {location}" if location else ""))

    # ── Shutdown ────────────────────────────────────────────────────────────

    def attach_stt(self, thread: "STTThread") -> None:
        """Keep a reference so closeEvent can stop the background thread."""
        self._stt = thread

    def keyPressEvent(self, event) -> None:
        # Esc (or Q) quits — fullscreen windows otherwise swallow Esc.
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Q):
            self.close()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        stt = getattr(self, "_stt", None)
        if stt is not None and stt.isRunning():
            # run_stt() blocks in recorder.text(); terminate is abrupt but
            # acceptable for a kiosk app shutting down.
            stt.terminate()
            stt.wait(2000)
        sys.stdout = sys.__stdout__        # restore original stdout
        event.accept()


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    app = QApplication(sys.argv)

    window = MirrorWindow()

    # Route every print() ([Ear]/[Voice]/[System]/[Router]/[AI]/[Executer])
    # into the on-screen terminal, while still teeing to the real console.
    log_stream = LogStream(tee=sys.__stdout__)
    log_stream.line.connect(window.append_log)   # queued across threads
    sys.stdout = log_stream

    ui_bus.command.connect(window.handle_ui_command)

    window.showFullScreen()              # use .show() while developing

    preload_models()                     # its logs stream into the terminal

    stt = STTThread()
    window.attach_stt(stt)
    stt.start()

    sys.exit(app.exec())                 # Qt event loop owns the main thread


if __name__ == "__main__":
    main()
