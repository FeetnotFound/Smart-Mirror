import json
import sys
from pathlib import Path
import dotenv
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QGridLayout, QVBoxLayout, QHBoxLayout,
    QStackedWidget,
)
from PySide6.QtCore import Qt, QThread, QTimer
import ui_backend.audio_backend as _audio
from ui_backend.schedule_backend import in_sleep_window, blank_display, unblank_display

# AI is optional — the mirror runs as a display-only device without it.
# Run install_ai.sh to add voice control.
try:
    from ai.llm import preload_models
    from ai.stt import run_stt, set_wake_word
    _AI_AVAILABLE = True
except Exception as _ai_err:
    print(f"[AI] voice pipeline disabled ({_ai_err})")
    print("[AI] run  bash install_ai.sh  to enable voice control")
    _AI_AVAILABLE    = False
    preload_models   = lambda: None
    run_stt          = lambda **kw: None
    def set_wake_word(name: str) -> None: pass
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
from web_config.server import start as start_web_config


dotenv.load_dotenv("variables.env")


def _load_settings() -> dict:
    defaults: dict = {
        "mirror_name": "MIRROR",
        "calendar_days": 7,
        "tts_enabled": True,
        "stt_enabled": True,
        "alsa_device": "",
        "alarm_volume": 0.5,
        "alarm_sound":  "",
        "widgets": {
            "terminal": True, "calendar": True, "tasks": True,
            "clock":    True, "next_up":  True, "timer": True,
            "alarm":    True, "system":   True,
        },
        "colors": {"text": "#dddddd", "mid": "#888888", "dim": "#444444"},
        "layout": {
            "top_left":    "terminal",
            "bottom_left": "tasks",
            "bottom_right": [
                ["clock", "next_up"],
                ["timer", "alarm"],
                ["system"],
            ],
        },
    }
    p = Path(__file__).parent / "settings.json"
    if not p.exists():
        return defaults
    try:
        on_disk = json.loads(p.read_text())
        merged  = dict(defaults)
        merged.update({k: v for k, v in on_disk.items()
                       if k not in ("widgets", "layout")})
        merged["widgets"] = dict(defaults["widgets"])
        merged["widgets"].update(on_disk.get("widgets", {}))
        merged["colors"] = dict(defaults["colors"])
        merged["colors"].update(on_disk.get("colors", {}))
        merged["layout"] = dict(defaults["layout"])
        merged["layout"].update(on_disk.get("layout", {}))
        return merged
    except Exception:
        return defaults

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
        self._stt        = None
        self._music_poll = None
        self._rebuild_ui()

    def _rebuild_ui(self) -> None:
        """Rebuild the entire Qt layout from settings.json — called on startup and on save."""
        from ui import theme as _theme

        _s = _load_settings()
        _theme.apply(_s.get("colors", {}))

        # Stop old music poll before deleting old widgets
        if self._music_poll is not None:
            self._music_poll.stop()
            self._music_poll = None

        root = QWidget()
        grid = QGridLayout(root)
        grid.setContentsMargins(28, 28, 28, 28)
        grid.setSpacing(28)

        _layout = _s.get("layout", {})

        # ── Create all widgets first ──────────────────────────────────────
        self.terminal       = Terminal(line_spacing=1.8)
        self.calendar_widget = CalendarWidget(days=_s["calendar_days"])
        self.task_widget    = TaskWidget()
        self.clock_widget   = ClockWidget()
        self.next_up_widget = NextUpWidget()
        self.timer_widget   = TimerWidget()
        self.alarm_widget   = AlarmWidget()
        self.system_widget  = SystemInfoWidget()
        self.music_widget   = MusicWidget()

        # System/Music share a stacked slot — auto-switches on AirPlay
        self._sys_stack = QStackedWidget()
        self._sys_stack.setFixedSize(440, 440)
        sp = self._sys_stack.sizePolicy()
        sp.setRetainSizeWhenHidden(True)
        self._sys_stack.setSizePolicy(sp)
        self._sys_stack.addWidget(self.system_widget)  # index 0
        self._sys_stack.addWidget(self.music_widget)   # index 1

        # Name → widget for layout-driven placement
        _named = {
            "terminal": self.terminal,
            "tasks":    self.task_widget,
            "clock":    self.clock_widget,
            "next_up":  self.next_up_widget,
            "timer":    self.timer_widget,
            "alarm":    self.alarm_widget,
            "system":   self._sys_stack,
        }

        # ── Place widgets according to layout settings ────────────────────
        _tl = _named.get(_layout.get("top_left", "terminal"), self.terminal)
        grid.addWidget(_tl, 0, 0,
                        Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        grid.addWidget(self.calendar_widget, 0, 1)

        # Accent bar — mirror name between the two content rows
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
        _name = _QL(_s["mirror_name"].upper())
        _name.setFont(_QF("Arial", 11, _QF.Weight.Light))
        _name.setStyleSheet(
            f"color: {_theme.text}; letter-spacing: 8px;"
            "background: transparent; font-style: normal;")

        _al.addWidget(_line_l, 1)
        _al.addWidget(_name)
        _al.addWidget(_line_r, 1)
        grid.addWidget(accent, 1, 0, 1, 2)

        _bl = _named.get(_layout.get("bottom_left", "tasks"), self.task_widget)
        grid.addWidget(_bl, 2, 0,
                        Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft)

        # Bottom-right cluster — column order driven by settings
        def _vstack(*widgets):
            w = QWidget()
            w.setStyleSheet("background: transparent;")
            v = QVBoxLayout(w)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(20)
            for ww in widgets:
                v.addWidget(ww)
            return w

        right_row = QWidget()
        right_layout = QHBoxLayout(right_row)
        right_layout.setAlignment(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)
        right_layout.setSpacing(28)
        right_layout.setContentsMargins(0, 0, 0, 0)

        _br_cols = _layout.get("bottom_right",
                                [["clock", "next_up"], ["timer", "alarm"], ["system"]])
        for col in _br_cols:
            col_ws = [_named[n] for n in col if n in _named]
            if not col_ws:
                continue
            right_layout.addWidget(col_ws[0] if len(col_ws) == 1 else _vstack(*col_ws))

        grid.addWidget(right_row, 2, 1,
                        Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)

        grid.setRowStretch(1, 1)
        grid.setColumnStretch(1, 1)

        # Swap in the new central widget (Qt deletes the old one)
        self.setCentralWidget(root)

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

        for _wname, _visible in _s["widgets"].items():
            if not _visible:
                _w = self._widgets.get(_wname)
                if _w:
                    _w.hide()

        self._music_poll = QTimer(self)
        self._music_poll.timeout.connect(self._sync_music_slot)
        self._music_poll.start(3_000)

        if _AI_AVAILABLE:
            set_wake_word(_s["mirror_name"])

        # Wire audio callbacks AFTER widgets set their own callbacks.
        # TimerWidget.__init__ sets on_finish to its signal emitter; we wrap it
        # so audio fires too. Must live here so rebuilds (settings saves) don't
        # silently drop the audio hook.
        from ui_backend.timer_backend import get_manager as _get_tmgr
        from ui_backend.alarm_backend import get_manager as _get_amgr
        _tmgr = _get_tmgr()
        _wcb  = _tmgr.on_finish
        def _on_timer_done(t, _wcb=_wcb):
            _audio.play_alert("timer")
            if _wcb:
                _wcb(t)
        _tmgr.on_finish = _on_timer_done
        _get_amgr().on_fire = lambda a: _audio.play_alert(
            "wakeup" if a.repeat_daily else "alarm"
        )

    def _sync_music_slot(self) -> None:
        """Switch the system-info slot to Music when AirPlay is active."""
        self._sys_stack.setCurrentIndex(1 if self.music_widget.is_playing else 0)

    # ── Logging ───────────────────────────────────────────────────────────

    def append_log(self, line: str) -> None:
        self.terminal.append_line(line)

    # ── UI control (called via Qt signal from worker thread) ───────────────

    def handle_ui_command(self, action: str, module: str,
                          location: str, size: str) -> None:
        if action == "reload":
            self._rebuild_ui()
            print("[UI] layout rebuilt from settings")
            return
        if action == "schedule":
            if _schedule_watcher is not None:
                _schedule_watcher._tick()
            return
        if action == "stt_start":
            self._start_stt()
            return
        if action == "stt_stop":
            self._stop_stt()
            return
        widget = self._widgets.get(module)
        if widget is None:
            print(f"[UI] unknown module: {module!r}")
            return
        if action == "show":
            widget.show()
        elif action == "hide":
            widget.hide()
        elif action == "refresh":
            if hasattr(widget, "_refresh"):
                widget._refresh()
        print(f"[UI] {action} {module}"
              + (f" at {location}" if location else ""))

    # ── Shutdown ────────────────────────────────────────────────────────────

    def attach_stt(self, thread: "STTThread") -> None:
        """Keep a reference so closeEvent can stop the background thread."""
        self._stt = thread

    def _start_stt(self) -> None:
        if not _AI_AVAILABLE or self._stt is not None:
            return
        preload_models()
        stt = STTThread()
        self.attach_stt(stt)
        stt.start()
        print("[UI] STT started")

    def _stop_stt(self) -> None:
        stt = getattr(self, "_stt", None)
        if stt is None:
            return
        stt.terminate()
        stt.wait(3000)
        self._stt = None
        print("[UI] STT stopped")

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


_schedule_watcher: "_ScheduleWatcher | None" = None

# ── Display schedule watcher ──────────────────────────────────────────────────

class _ScheduleWatcher:
    """Checks the sleep/wake schedule every minute and blanks/unblanks the display."""

    def __init__(self) -> None:
        self._sleeping: bool | None = None   # None = unknown (first tick)
        self._timer = QTimer()
        self._timer.timeout.connect(self._tick)
        self._timer.start(60_000)
        self._tick()

    def _tick(self) -> None:
        s = _load_settings().get("schedule", {})
        if not s.get("enabled", False):
            if self._sleeping is True:
                # Schedule was disabled while screen was blanked — restore it.
                unblank_display()
            self._sleeping = None
            return

        sleeping = in_sleep_window(
            s.get("sleep_time", "23:00"),
            s.get("wake_time",  "07:00"),
        )

        if sleeping and self._sleeping is False:
            blank_display()
        elif not sleeping and self._sleeping is True:
            unblank_display()
            if s.get("wakeup_sound", True):
                _audio.play("wakeup.wav")
        elif self._sleeping is None:
            # First tick — sync display state without playing sounds.
            if sleeping:
                blank_display()
            else:
                unblank_display()

        self._sleeping = sleeping


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    app = QApplication(sys.argv)

    window = MirrorWindow()

    # Route every print() ([Ear]/[Voice]/[System]/[Router]/[AI]/[Executer])
    # into the on-screen terminal, while still teeing to the real console.
    log_stream = LogStream(tee=sys.__stdout__)
    log_stream.line.connect(window.append_log)   # queued across threads
    sys.stdout = log_stream

    # QueuedConnection guarantees the slot runs on the Qt main thread
    # even when ui_bus.command is emitted from the HTTP server's Python thread.
    ui_bus.command.connect(window.handle_ui_command,
                           Qt.ConnectionType.QueuedConnection)

    start_web_config()

    window.showFullScreen()              # use .show() while developing

    # Start the display schedule watcher (kept alive by the event loop).
    global _schedule_watcher
    _schedule_watcher = _ScheduleWatcher()

    if _AI_AVAILABLE and _load_settings().get("stt_enabled", True):
        preload_models()
        stt = STTThread()
        window.attach_stt(stt)
        stt.start()

    sys.exit(app.exec())                 # Qt event loop owns the main thread


if __name__ == "__main__":
    main()
