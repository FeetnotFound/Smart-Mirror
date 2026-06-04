"""Timer backend — local countdown timers with SQLite persistence.

Router signature:  set_timer(duration, label)

Timers survive restarts by storing their absolute UTC deadline in SQLite.
On startup any unexpired timers are automatically resumed; expired ones
(the mirror was off when they would have fired) are discarded silently.
"""
import re
import time
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

DB_PATH = Path(__file__).resolve().parent / "data" / "timers.db"

# ── duration parsing ──────────────────────────────────────────────────────────
_UNIT_SECONDS = {"h": 3600, "hr": 3600, "hour": 3600, "hours": 3600,
                 "m": 60, "min": 60, "minute": 60, "minutes": 60,
                 "s": 1, "sec": 1, "second": 1, "seconds": 1}
_TOKEN_RE = re.compile(r"(\d+(?:\.\d+)?)\s*([a-z]+)")

_WORD_TO_DIGIT = {
    "a": "1", "an": "1",
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
    "eleven": "11", "twelve": "12", "thirteen": "13", "fourteen": "14",
    "fifteen": "15", "sixteen": "16", "seventeen": "17", "eighteen": "18",
    "nineteen": "19", "twenty": "20", "thirty": "30", "forty": "40",
    "forty-five": "45", "fifty": "50",
}
_WORD_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in sorted(_WORD_TO_DIGIT, key=len, reverse=True)) + r")\b",
    re.I,
)


def _normalize_words(text: str) -> str:
    """Replace spoken number words with digits: 'five minutes' -> '5 minutes'."""
    return _WORD_RE.sub(lambda m: _WORD_TO_DIGIT[m.group(1).lower()], text)


def parse_duration(text: str) -> int:
    """'1h30m' / '90 seconds' / 'five minutes' -> total seconds. Raises ValueError."""
    text = _normalize_words(str(text).strip().lower())
    total = 0.0
    matched = False
    for amount, unit in _TOKEN_RE.findall(text):
        secs = _UNIT_SECONDS.get(unit)
        if secs is None:
            raise ValueError(f"Unknown time unit: {unit!r}")
        total += float(amount) * secs
        matched = True
    if not matched:
        if text.replace(".", "", 1).isdigit():
            return int(float(text) * 60)
        raise ValueError(f"Could not parse duration: {text!r}")
    return int(total)


# ── timer model ───────────────────────────────────────────────────────────────
@dataclass
class Timer:
    id: int
    label: str
    total_seconds: int
    deadline_utc: str   # ISO-8601 UTC string — survives reboots

    @property
    def _deadline_dt(self) -> datetime:
        dt = datetime.fromisoformat(self.deadline_utc)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    @property
    def remaining(self) -> int:
        return max(0, int((self._deadline_dt - datetime.now(timezone.utc)).total_seconds()))

    @property
    def finished(self) -> bool:
        return self.remaining <= 0


# ── manager ───────────────────────────────────────────────────────────────────
class TimerManager:
    """Owns active timers. One background thread ticks all of them.

    Callbacks (set by the widget):
        on_tick(timer)    — ~1/sec per active timer
        on_finish(timer)  — once when a timer hits zero
    """

    def __init__(self, db_path: Path = DB_PATH) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._timers: dict[int, Timer] = {}
        self._lock = threading.Lock()
        self.on_tick: Optional[Callable[[Timer], None]] = None
        self.on_finish: Optional[Callable[[Timer], None]] = None
        self._init_db()
        self._load_persisted()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def _init_db(self) -> None:
        with self._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS timers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT,
                total_seconds INTEGER,
                deadline_utc TEXT)""")

    def _load_persisted(self) -> None:
        """Resume unexpired timers from the last session; drop expired ones."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT id, label, total_seconds, deadline_utc FROM timers"
            ).fetchall()
        expired_ids = []
        with self._lock:
            for row in rows:
                t = Timer(*row)
                if t.finished:
                    expired_ids.append(t.id)
                else:
                    self._timers[t.id] = t
        if expired_ids:
            with self._conn() as c:
                c.executemany("DELETE FROM timers WHERE id=?",
                              [(i,) for i in expired_ids])

    def set_timer(self, duration: str, label: str = "") -> Timer:
        secs = parse_duration(duration)
        deadline = datetime.now(timezone.utc) + timedelta(seconds=secs)
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO timers (label, total_seconds, deadline_utc) VALUES (?,?,?)",
                (label or "Timer", secs, deadline.isoformat()),
            )
            tid = cur.lastrowid
        t = Timer(id=tid, label=label or "Timer",
                  total_seconds=secs, deadline_utc=deadline.isoformat())
        with self._lock:
            self._timers[tid] = t
        return t

    def cancel(self, timer_id: int) -> bool:
        with self._lock:
            removed = self._timers.pop(timer_id, None) is not None
        if removed:
            with self._conn() as c:
                c.execute("DELETE FROM timers WHERE id=?", (timer_id,))
        return removed

    def active(self) -> list[Timer]:
        with self._lock:
            return list(self._timers.values())

    def _loop(self) -> None:
        while True:
            time.sleep(0.25)
            with self._lock:
                items = list(self._timers.items())
            for tid, t in items:
                if t.finished:
                    with self._lock:
                        self._timers.pop(tid, None)
                    with self._conn() as c:
                        c.execute("DELETE FROM timers WHERE id=?", (tid,))
                    if self.on_finish:
                        self.on_finish(t)
                elif self.on_tick:
                    self.on_tick(t)


# ── Router entry point ────────────────────────────────────────────────────────
_manager: Optional[TimerManager] = None


def get_manager() -> TimerManager:
    global _manager
    if _manager is None:
        _manager = TimerManager()
    return _manager


def set_timer(duration: str, label: str = "") -> str:
    """Called by the executer. Returns a spoken-friendly confirmation."""
    t = get_manager().set_timer(duration, label)
    mins, secs = divmod(t.total_seconds, 60)
    human = f"{mins} minute{'s' if mins != 1 else ''}" if mins else f"{secs} seconds"
    return f"Timer set for {human}."
