"""Light control backend — Hue + LIFX + Home Assistant, with a SQLite registry.

Router signature:  control_light(action, device_name, brightness, color)

Design
------
The three systems don't share an addressing model, so we don't try to unify
discovery. Instead a single SQLite table `lights` maps a friendly NAME you
choose -> the SYSTEM it lives on + that system's NATIVE identifier:

    • hue : native id is the bridge's integer light id   (e.g. "3")
    • lifx: native id is the device MAC                    (e.g. "d0:73:d5:..")
    • ha  : native id is the entity_id                     (e.g. "light.kitchen")

You populate the table ONCE via the discovery/import helpers below, then
`control_light("on", "kitchen")` looks the name up and dispatches to the right
adapter. Nothing is re-discovered on every command.

Credentials (read from env — never hardcode):
    • Hue : HUE_BRIDGE_IP, HUE_USERNAME           (username = the pairing token)
    • HA  : HA_BASE_URL,  HA_TOKEN                 (long-lived access token)
    • LIFX: nothing (LAN UDP discovery by MAC)

Optional deps — only the systems you actually use need their lib installed:
    pip install phue        # Hue
    pip install lifxlan     # LIFX
    # Home Assistant uses `requests`, already a core dep.

One-time setup, e.g. from a python shell:
    from light_backend import get_registry, discover_hue, discover_lifx
    discover_hue()                       # press the bridge button first
    discover_lifx()                      # finds bulbs on the LAN
    get_registry().add("kitchen", "ha", "light.kitchen")   # HA added by hand
"""
import os
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).resolve().parent / "data" / "lights.db"

VALID_SYSTEMS = {"hue", "lifx", "ha"}


# ── registry ──────────────────────────────────────────────────────────────
@dataclass
class Light:
    name: str          # friendly name, what the user says ("kitchen")
    system: str        # "hue" | "lifx" | "ha"
    native_id: str     # bridge int id / MAC / entity_id, as a string


class LightRegistry:
    def __init__(self, db_path: Path = DB_PATH) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def _init_db(self) -> None:
        with self._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS lights (
                name TEXT PRIMARY KEY,
                system TEXT NOT NULL,
                native_id TEXT NOT NULL)""")

    def add(self, name: str, system: str, native_id: str) -> Light:
        system = str(system).lower().strip()
        if system not in VALID_SYSTEMS:
            raise ValueError(f"system must be one of {VALID_SYSTEMS}, got {system!r}")
        name = str(name).lower().strip()
        with self._lock, self._conn() as c:
            c.execute("""INSERT INTO lights (name, system, native_id)
                         VALUES (?,?,?)
                         ON CONFLICT(name) DO UPDATE SET
                             system=excluded.system,
                             native_id=excluded.native_id""",
                      (name, system, str(native_id)))
        return Light(name, system, str(native_id))

    def remove(self, name: str) -> bool:
        with self._lock, self._conn() as c:
            return c.execute("DELETE FROM lights WHERE name=?",
                             (str(name).lower().strip(),)).rowcount > 0

    def get(self, name: str) -> Optional[Light]:
        with self._conn() as c:
            r = c.execute("SELECT name, system, native_id FROM lights WHERE name=?",
                          (str(name).lower().strip(),)).fetchone()
        return Light(*r) if r else None

    def list(self) -> list[Light]:
        with self._conn() as c:
            return [Light(*r) for r in c.execute(
                "SELECT name, system, native_id FROM lights ORDER BY name")]


_registry: Optional[LightRegistry] = None


def get_registry() -> LightRegistry:
    global _registry
    if _registry is None:
        _registry = LightRegistry()
    return _registry


# ── adapters ────────────────────────────────────────────────────────────────
# Each adapter does the real work for ONE system. They raise on failure; the
# dispatcher below turns that into a spoken "couldn't reach" message. Adapters
# are cached so we don't reconnect to the bridge / re-scan the LAN per command.

class _HueAdapter:
    """Philips Hue via the local bridge (phue)."""
    def __init__(self) -> None:
        self._bridge = None

    def _connect(self):
        if self._bridge is not None:
            return self._bridge
        from phue import Bridge  # lazy import so missing dep doesn't break others
        ip = os.environ.get("HUE_BRIDGE_IP")
        user = os.environ.get("HUE_USERNAME")
        if not ip:
            raise RuntimeError("HUE_BRIDGE_IP not set")
        # phue stores/uses the username token; if absent it pairs on first call
        # (requires the physical bridge button pressed within 30s).
        self._bridge = Bridge(ip, username=user) if user else Bridge(ip)
        self._bridge.connect()
        return self._bridge

    def apply(self, native_id: str, on: bool,
              brightness: Optional[int], color: Optional[str]) -> None:
        bridge = self._connect()
        lid = int(native_id)
        cmd: dict = {"on": on}
        if on and brightness is not None:
            cmd["bri"] = _pct_to_255(brightness)
        if on and color is not None:
            xy = _hue_xy(color)
            if xy:
                cmd["xy"] = xy
        bridge.set_light(lid, cmd)

    def discover(self) -> list[tuple[str, str]]:
        """Returns [(suggested_name, native_id), ...] for every bridge light."""
        import requests as _req
        bridge = self._connect()
        ip = os.environ.get("HUE_BRIDGE_IP", "")
        # Query the bridge REST API directly — avoids phue's get_light_objects()
        # which fails on newer bridge firmware that uses non-integer light IDs.
        resp = _req.get(f"http://{ip}/api/{bridge.username}/lights", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            # Bridge returned an error list: [{"error": {"description": "..."}}]
            msgs = [e.get("error", {}).get("description", str(e)) for e in data]
            raise RuntimeError(f"Hue bridge error: {'; '.join(msgs)}")
        return [(str(v["name"]).lower(), str(k))
                for k, v in data.items()
                if isinstance(v, dict) and "name" in v]



class _LifxAdapter:
    """LIFX over the LAN (lifxlan). Addressed by MAC; rediscovered by MAC if IP moves."""
    def __init__(self) -> None:
        self._lan = None
        self._by_mac: dict[str, object] = {}

    def _lan_obj(self):
        if self._lan is None:
            from lifxlan import LifxLAN
            self._lan = LifxLAN()
        return self._lan

    def _device(self, mac: str):
        dev = self._by_mac.get(mac)
        if dev is not None:
            return dev
        # find the device with this MAC among discovered lights
        for d in self._lan_obj().get_lights():
            if str(d.get_mac_addr()).lower() == mac.lower():
                self._by_mac[mac] = d
                return d
        raise RuntimeError(f"LIFX device {mac} not found on the network")

    def apply(self, native_id: str, on: bool,
              brightness: Optional[int], color: Optional[str]) -> None:
        dev = self._device(native_id)
        dev.set_power("on" if on else "off")
        if on and brightness is not None:
            # lifx brightness is 0..65535
            dev.set_brightness(int(_clamp_pct(brightness) / 100 * 65535))
        if on and color is not None:
            hsbk = _lifx_hsbk(color)
            if hsbk:
                dev.set_color(hsbk)

    def discover(self) -> list[tuple[str, str]]:
        out = []
        for d in self._lan_obj().get_lights():
            try:
                name = str(d.get_label()).lower()
            except Exception:
                name = str(d.get_mac_addr())
            out.append((name, str(d.get_mac_addr())))
        return out


class _HaAdapter:
    """Home Assistant via REST. Addressed by entity_id; nothing to discover."""
    def __init__(self) -> None:
        import requests
        self._requests = requests
        self._base = (os.environ.get("HA_BASE_URL") or "").rstrip("/")
        self._token = os.environ.get("HA_TOKEN")

    def _headers(self) -> dict:
        if not self._base or not self._token:
            raise RuntimeError("HA_BASE_URL or HA_TOKEN not set")
        return {"Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json"}

    def apply(self, native_id: str, on: bool,
              brightness: Optional[int], color: Optional[str]) -> None:
        service = "turn_on" if on else "turn_off"
        body: dict = {"entity_id": native_id}
        if on and brightness is not None:
            body["brightness_pct"] = _clamp_pct(brightness)
        if on and color is not None:
            body["color_name"] = str(color).lower()
        r = self._requests.post(
            f"{self._base}/api/services/light/{service}",
            headers=self._headers(), json=body, timeout=5)
        r.raise_for_status()


_adapters: dict[str, object] = {}


def _adapter(system: str):
    if system not in _adapters:
        _adapters[system] = {"hue": _HueAdapter,
                             "lifx": _LifxAdapter,
                             "ha": _HaAdapter}[system]()
    return _adapters[system]


# ── colour / brightness helpers ──────────────────────────────────────────────
def _clamp_pct(v) -> int:
    try:
        return max(0, min(100, int(v)))
    except (TypeError, ValueError):
        return 100


def _pct_to_255(v) -> int:
    return int(_clamp_pct(v) / 100 * 254)


# Minimal named-colour table. Extend as you like. Returned formats differ per
# system, so each adapter converts from this RGB source of truth.
_NAMED_RGB = {
    "red": (255, 0, 0), "green": (0, 255, 0), "blue": (0, 0, 255),
    "white": (255, 255, 255), "warm": (255, 197, 143), "cool": (201, 226, 255),
    "yellow": (255, 255, 0), "orange": (255, 140, 0), "purple": (160, 32, 240),
    "pink": (255, 105, 180), "cyan": (0, 255, 255),
}


def _rgb(color: str):
    return _NAMED_RGB.get(str(color).lower().strip())


def _hue_xy(color: str):
    """RGB -> CIE xy for Hue. Returns [x, y] or None."""
    rgb = _rgb(color)
    if not rgb:
        return None
    r, g, b = [c / 255 for c in rgb]
    # gamma
    r, g, b = [(c / 12.92) if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
               for c in (r, g, b)]
    X = r * 0.649926 + g * 0.103455 + b * 0.197109
    Y = r * 0.234327 + g * 0.743075 + b * 0.022598
    Z = r * 0.0000000 + g * 0.053077 + b * 1.035763
    s = X + Y + Z
    if s == 0:
        return None
    return [round(X / s, 4), round(Y / s, 4)]


def _lifx_hsbk(color: str):
    """RGB -> LIFX [hue, saturation, brightness, kelvin] (0..65535). None if unknown."""
    import colorsys
    rgb = _rgb(color)
    if not rgb:
        return None
    r, g, b = [c / 255 for c in rgb]
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    return [int(h * 65535), int(s * 65535), int(v * 65535), 3500]


# ── public API ────────────────────────────────────────────────────────────
def _set_one(light: Light, on: bool,
             brightness: Optional[int], color: Optional[str]) -> bool:
    try:
        _adapter(light.system).apply(light.native_id, on, brightness, color)
        return True
    except Exception as e:  # noqa: BLE001 - adapters raise many lib-specific errors
        print(f"[light] {light.system}:{light.name} failed: {e}")
        return False


def control_light(action: str, device_name: str = "all",
                  brightness: Optional[int] = None,
                  color: Optional[str] = None) -> str:
    """Router entry point. action in {on,turn_on,off,turn_off}. device_name is a
    friendly name from the registry, or "all" to hit every registered light."""
    on = str(action).lower() in ("on", "turn_on")
    reg = get_registry()
    name = str(device_name).lower().strip()

    if name in ("all", "", "lights", "the lights"):
        lights = reg.list()
        if not lights:
            return "I don't have any lights set up yet."
        results = [_set_one(l, on, brightness, color) for l in lights]
        if not any(results):
            return "I couldn't reach the lights."
        verb = "Turning on" if on else "Turning off"
        if all(results):
            return f"{verb} all the lights."
        return f"{verb} the lights — some didn't respond."

    light = reg.get(name)
    if light is None:
        return f"I don't know a light called {device_name}."
    if not _set_one(light, on, brightness, color):
        return f"I couldn't reach {device_name}."
    return f"{'Turning on' if on else 'Turning off'} {device_name}."


# ── one-time discovery helpers ──────────────────────────────────────────────
def discover_hue(prefix: str = "") -> list[Light]:
    """Pair (press bridge button first), read every bridge light, store it.
    `prefix` lets you namespace names, e.g. prefix='hue ' -> 'hue kitchen'."""
    reg = get_registry()
    added = []
    for name, native_id in _adapter("hue").discover():
        added.append(reg.add(f"{prefix}{name}", "hue", native_id))
    return added


def discover_lifx(prefix: str = "") -> list[Light]:
    reg = get_registry()
    added = []
    for name, native_id in _adapter("lifx").discover():
        added.append(reg.add(f"{prefix}{name}", "lifx", native_id))
    return added