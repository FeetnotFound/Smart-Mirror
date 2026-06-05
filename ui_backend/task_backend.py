"""Task backend — a persistent to-do list.

Router signature:  add_task(text, priority)

You asked for: add task, check off task, "and stuff like that". So the backend
exposes add / complete / delete / list. Voice only gives you `add_task`; the
others are driven by the widget (tap to check off) — the router has no
complete_task function, which is fine because checking off is a UI action,
not a spoken one. If you DO want "Mirror, mark the laundry done" by voice,
that needs a new router function + retraining. Flagging, not assuming.
"""
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).resolve().parent / "data" / "tasks.db"

_PRIORITY = {"low": 0, "normal": 1, "medium": 1, "high": 2, "urgent": 3}


@dataclass
class Task:
    id: int
    text: str
    priority: int
    done: bool
    created_iso: str


class TaskManager:
    def __init__(self, db_path: Path = DB_PATH) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def _init_db(self) -> None:
        with self._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT, priority INTEGER DEFAULT 1,
                done INTEGER DEFAULT 0, created_iso TEXT)""")

    def add(self, text: str, priority: str = "normal") -> Task:
        prio = _PRIORITY.get(str(priority).lower(), 1) if not str(priority).isdigit() else int(priority)
        now = datetime.now().isoformat()
        with self._lock, self._conn() as c:
            cur = c.execute(
                "INSERT INTO tasks (text, priority, created_iso) VALUES (?,?,?)",
                (text, prio, now))
            return Task(cur.lastrowid, text, prio, False, now)

    def complete(self, task_id: int, done: bool = True) -> bool:
        with self._lock, self._conn() as c:
            return c.execute("UPDATE tasks SET done=? WHERE id=?",
                             (int(done), task_id)).rowcount > 0

    def delete(self, task_id: int) -> bool:
        with self._lock, self._conn() as c:
            return c.execute("DELETE FROM tasks WHERE id=?", (task_id,)).rowcount > 0

    def list(self, include_done: bool = True) -> list[Task]:
        q = "SELECT id, text, priority, done, created_iso FROM tasks"
        if not include_done:
            q += " WHERE done=0"
        q += " ORDER BY done ASC, priority DESC, id ASC"
        with self._conn() as c:
            return [Task(r[0], r[1], r[2], bool(r[3]), r[4]) for r in c.execute(q)]


_manager: Optional[TaskManager] = None


def get_manager() -> TaskManager:
    global _manager
    if _manager is None:
        _manager = TaskManager()
    return _manager


def add_task(text: str, priority: str = "normal") -> str:
    get_manager().add(text, priority)
    return f"Added: {text}."


def complete_task(text: str) -> str:
    """Mark the first undone task whose text contains `text` as done."""
    mgr = get_manager()
    needle = text.lower().strip()
    for task in mgr.list(include_done=False):
        if needle in task.text.lower() or task.text.lower() in needle:
            mgr.complete(task.id, True)
            return f"Marked done: {task.text}."
    return f"I couldn't find a task matching '{text}'."
