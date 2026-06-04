"""Smart plug backend — TP-Link/Tapo (python-kasa) + Home Assistant.

Router signature:  control_plug(action, device_name)

Intertwines with light_backend: same HA credentials, same registry pattern.
Plugs and lights live in separate SQLite tables so names don't collide.

Supported systems:
    ha   — Home Assistant via REST switch service (HA_BASE_URL, HA_TOKEN)
    kasa — TP-Link / Tapo via python-kasa, native_id is the device IP
             pip install python-kasa

One-time setup from a Python shell:
    from plug_backend import get_registry
    get_registry().add("coffee maker", "kasa", "192.168.1.42")
    get_registry().add("fan",          "ha",   "switch.bedroom_fan")
"""
import os
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).resolve().parent / "data" / "plugs.db"
VALID_SYSTEMS = {"ha", "kasa"}


@dataclass
class Plug:
    name: str
    system: str
    native_id: str


class PlugRegistry:
    def __init__(self, db_path: Path = DB_PATH) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def _init_db(self) -> None:
        with self._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS plugs (
                name TEXT PRIMARY KEY,
                system TEXT NOT NULL,
                native_id TEXT NOT NULL)""")

    def add(self, name: str, system: str, native_id: str) -> Plug:
        system = str(system).lower().strip()
        if system not in VALID_SYSTEMS:
            raise ValueError(f"system must be one of {VALID_SYSTEMS}")
        name = str(name).lower().strip()
        with self._lock, self._conn() as c:
            c.execute("""INSERT INTO plugs (name, system, native_id) VALUES (?,?,?)
                         ON CONFLICT(name) DO UPDATE SET
                             system=excluded.system,
                             native_id=excluded.native_id""",
                      (name, system, str(native_id)))
        return Plug(name, system, str(native_id))

    def remove(self, name: str) -> bool:
        with self._lock, self._conn() as c:
            return c.execute("DELETE FROM plugs WHERE name=?",
                             (str(name).lower().strip(),)).rowcount > 0

    def get(self, name: str) -> Optional[Plug]:
        with self._conn() as c:
            r = c.execute("SELECT name, system, native_id FROM plugs WHERE name=?",
                          (str(name).lower().strip(),)).fetchone()
        return Plug(*r) if r else None

    def list(self) -> list[Plug]:
        with self._conn() as c:
            return [Plug(*r) for r in c.execute(
                "SELECT name, system, native_id FROM plugs ORDER BY name")]


_registry: Optional[PlugRegistry] = None


def get_registry() -> PlugRegistry:
    global _registry
    if _registry is None:
        _registry = PlugRegistry()
    return _registry


# ── adapters ──────────────────────────────────────────────────────────────────

def _apply_ha(native_id: str, on: bool) -> None:
    import requests
    base = (os.environ.get("HA_BASE_URL") or "").rstrip("/")
    token = os.environ.get("HA_TOKEN")
    if not base or not token:
        raise RuntimeError("HA_BASE_URL or HA_TOKEN not set")
    service = "turn_on" if on else "turn_off"
    r = requests.post(
        f"{base}/api/services/switch/{service}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"entity_id": native_id}, timeout=5)
    r.raise_for_status()


def _apply_kasa(native_id: str, on: bool) -> None:
    try:
        import asyncio
        from kasa import SmartPlug
    except ImportError:
        raise RuntimeError("python-kasa not installed — pip install python-kasa")

    async def _run():
        plug = SmartPlug(native_id)
        await plug.update()
        if on:
            await plug.turn_on()
        else:
            await plug.turn_off()

    asyncio.run(_run())


def _apply(plug: Plug, on: bool) -> bool:
    try:
        if plug.system == "ha":
            _apply_ha(plug.native_id, on)
        elif plug.system == "kasa":
            _apply_kasa(plug.native_id, on)
        return True
    except Exception as e:
        print(f"[plug] {plug.system}:{plug.name} failed: {e}")
        return False


def control_plug(action: str, device_name: str = "all") -> str:
    """Router entry point. action in {on, turn_on, off, turn_off}."""
    on = str(action).lower() in ("on", "turn_on")
    reg = get_registry()
    name = str(device_name).lower().strip()

    if name in ("all", "", "plugs"):
        plugs = reg.list()
        if not plugs:
            return "I don't have any plugs set up yet."
        results = [_apply(p, on) for p in plugs]
        verb = "Turning on" if on else "Turning off"
        if all(results):
            return f"{verb} all the plugs."
        if not any(results):
            return "I couldn't reach the plugs."
        return f"{verb} the plugs — some didn't respond."

    plug = reg.get(name)
    if plug is None:
        return f"I don't know a plug called {device_name}."
    if not _apply(plug, on):
        return f"I couldn't reach {device_name}."
    return f"{'Turning on' if on else 'Turning off'} {device_name}."
