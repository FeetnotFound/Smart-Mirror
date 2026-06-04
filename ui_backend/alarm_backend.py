"""Alarm backend — wall-clock alarms.

Router signature:  set_alarm(time, label)

Unlike timers (relative), alarms fire at an absolute time of day. They persist
to SQLite so a mirror reboot doesn't lose them. One thread checks every few
seconds whether any alarm's target time has passed.
"""
import re
import sqlite3
import threading
import time as _time
from datetime import datetime, timedelta
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

DB_PATH = Path(__file__).resolve().parent / "data" / "alarms.db"

# time parsing ───────────────────────────────────────────────────────────────
_HHMM_RE = re.compile(r"(\d{1,2})(?:[:\s](\d{2}))?\s*(am|pm)?", re.I)

_WORD_TO_DIGIT = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
    "eleven": "11", "twelve": "12", "thirteen": "13", "fourteen": "14",
    "fifteen": "15", "sixteen": "16", "seventeen": "17", "eighteen": "18",
    "nineteen": "19", "twenty": "20", "thirty": "30", "forty": "40",
    "forty-five": "45", "fifty": "50", "oh": "0",
}
_WORD_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in sorted(_WORD_TO_DIGIT, key=len, reverse=True)) + r")\b",
    re.I,
)


def _normalize_words(text: str) -> str:
    return _WORD_RE.sub(lambda m: _WORD_TO_DIGIT[m.group(1).lower()], text)


def parse_time(text: str) -> datetime:
    """'7am' / 'seven thirty pm' / '06:45' -> next datetime. Raises ValueError."""
    m = _HHMM_RE.search(_normalize_words(str(text).strip().lower()))
    if not m:
        raise ValueError(f"Could not parse time: {text!r}")
    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    meridiem = m.group(3)
    if meridiem == "pm" and hour < 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ValueError(f"Invalid time: {text!r}")
    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:                      # already passed today -> tomorrow
        target += timedelta(days=1)
    return target


@dataclass
class Alarm:
    id: int
    label: str
    target_iso: str

    @property
    def target(self) -> datetime:
        return datetime.fromisoformat(self.target_iso)


class AlarmManager:
    def __init__(self, db_path: Path = DB_PATH) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()
        self.on_fire: Optional[Callable[[Alarm], None]] = None
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def _init_db(self) -> None:
        with self._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS alarms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT, target_iso TEXT, fired INTEGER DEFAULT 0)""")

    def set_alarm(self, time_str: str, label: str = "") -> Alarm:
        target = parse_time(time_str)
        with self._lock, self._conn() as c:
            cur = c.execute(
                "INSERT INTO alarms (label, target_iso) VALUES (?, ?)",
                (label or "Alarm", target.isoformat()),
            )
            return Alarm(id=cur.lastrowid, label=label or "Alarm",
                         target_iso=target.isoformat())

    def active(self) -> list[Alarm]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT id, label, target_iso FROM alarms WHERE fired=0").fetchall()
        return [Alarm(*r) for r in rows]

    def cancel(self, alarm_id: int) -> bool:
        with self._lock, self._conn() as c:
            return c.execute("DELETE FROM alarms WHERE id=?", (alarm_id,)).rowcount > 0

    def _loop(self) -> None:
        while True:
            _time.sleep(5)
            now = datetime.now()
            for a in self.active():
                if a.target <= now:
                    with self._lock, self._conn() as c:
                        c.execute("UPDATE alarms SET fired=1 WHERE id=?", (a.id,))
                    if self.on_fire:
                        self.on_fire(a)


_manager: Optional[AlarmManager] = None


def get_manager() -> AlarmManager:
    global _manager
    if _manager is None:
        _manager = AlarmManager()
    return _manager


def set_alarm(time: str, label: str = "") -> str:
    a = get_manager().set_alarm(time, label)
    return f"Alarm set for {a.target.strftime('%I:%M %p').lstrip('0')}."
