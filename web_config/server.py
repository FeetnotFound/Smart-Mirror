"""Web config server — runs in a background daemon thread alongside the Qt app.

Uses Python's built-in http.server (no Flask) to avoid threading conflicts with
the Qt event loop. Access from any device on the same network at port 5000.
"""
import http.server
import json
import os
import socket
import socketserver
import sqlite3
import subprocess
import sys
import threading
from pathlib import Path

from ui_backend.ui_control_backend import ui_bus

_ROOT         = Path(__file__).resolve().parent.parent
SETTINGS_PATH = _ROOT / "settings.json"
STATIC_PATH   = Path(__file__).resolve().parent / "static"
DB_PATH       = _ROOT / "ui_backend" / "data" / "calendar.db"

_DEFAULTS: dict = {
    "mirror_name": "MILLER",
    "calendar_days": 7,
    "widgets": {
        "terminal": True,
        "calendar": True,
        "tasks":    True,
        "clock":    True,
        "next_up":  True,
        "timer":    True,
        "alarm":    True,
        "system":   True,
    },
}

_lock = threading.Lock()


def load_settings() -> dict:
    merged = _deep_merge({}, _DEFAULTS)
    if SETTINGS_PATH.exists():
        try:
            merged = _deep_merge(merged, json.loads(SETTINGS_PATH.read_text()))
        except Exception:
            pass
    return merged


def save_settings(data: dict) -> None:
    SETTINGS_PATH.write_text(json.dumps(data, indent=2))


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


# ── Request handler ───────────────────────────────────────────────────────────

class _Handler(http.server.BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass  # suppress per-request console noise

    # ── response helpers ──────────────────────────────────────────────────
    def _send_json(self, data, status: int = 200) -> None:
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, path: Path) -> None:
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        n = int(self.headers.get("Content-Length", 0))
        if n <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(n))
        except Exception:
            return {}

    # ── GET ───────────────────────────────────────────────────────────────
    def do_GET(self):
        path = self.path.split("?")[0]
        try:
            if path == "/":
                self._send_html(STATIC_PATH / "index.html")

            elif path == "/api/settings":
                self._send_json(load_settings())

            elif path == "/api/calendar-colors":
                if not DB_PATH.exists():
                    self._send_json([])
                    return
                with sqlite3.connect(str(DB_PATH), timeout=2.0) as c:
                    rows = c.execute(
                        "SELECT name, color FROM calendar_colors ORDER BY name"
                    ).fetchall()
                self._send_json([{"name": r[0], "color": r[1]} for r in rows])

            elif path == "/api/env":    self._get_env()
            elif path == "/api/models": self._get_models()
            elif path == "/api/lights": self._get_lights()
            elif path == "/api/plugs":  self._get_plugs()

            else:
                self._send_json({"error": "not found"}, 404)

        except Exception as e:
            try:
                self._send_json({"error": str(e)}, 500)
            except Exception:
                pass

    # ── GET (extra routes) ────────────────────────────────────────────────
    def _get_models(self):
        import urllib.request as _ur
        try:
            with _ur.urlopen("http://localhost:11434/api/tags", timeout=3) as r:
                data = json.loads(r.read())
            names = sorted(m["name"] for m in data.get("models", []))
        except Exception:
            names = []
        current = load_settings().get("ai_model", "")
        self._send_json({"models": names, "current": current})

    def _get_env(self):
        env_path = _ROOT / "variables.env"
        result = {}
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    result[k.strip()] = v.strip()
        self._send_json(result)

    def _get_lights(self):
        try:
            from ui_backend.light_backend import get_registry
            lights = [{"name": l.name, "system": l.system, "native_id": l.native_id}
                      for l in get_registry().list()]
            self._send_json(lights)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _get_plugs(self):
        try:
            from ui_backend.plug_backend import get_registry
            plugs = [{"name": p.name, "system": p.system, "native_id": p.native_id}
                     for p in get_registry().list()]
            self._send_json(plugs)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    # ── POST ──────────────────────────────────────────────────────────────
    def do_POST(self):
        path = self.path.split("?")[0]
        data = self._read_json()
        try:
            if path == "/api/settings":
                with _lock:
                    current = load_settings()
                    if "mirror_name" in data:
                        current["mirror_name"] = str(data["mirror_name"])[:40]
                    if "calendar_days" in data:
                        try:
                            current["calendar_days"] = max(3, min(14, int(data["calendar_days"])))
                        except (ValueError, TypeError):
                            pass
                    if "colors" in data and isinstance(data["colors"], dict):
                        if "colors" not in current:
                            current["colors"] = {}
                        current["colors"].update(
                            {k: str(v) for k, v in data["colors"].items()})
                    if "layout" in data and isinstance(data["layout"], dict):
                        current["layout"] = data["layout"]
                    if "ai_model" in data:
                        current["ai_model"] = str(data["ai_model"])[:80]
                    if "widgets" in data:
                        for name, visible in data["widgets"].items():
                            if name in current["widgets"]:
                                current["widgets"][name] = bool(visible)
                                try:
                                    ui_bus.command.emit(
                                        "show" if visible else "hide", name, "", "")
                                except Exception as e:
                                    print(f"[WebConfig] emit failed: {e}")
                    save_settings(current)
                try:
                    ui_bus.command.emit("reload", "", "", "")
                except Exception:
                    pass
                self._send_json({"ok": True})

            elif path == "/api/calendar-colors":
                name  = str(data.get("name",  "")).strip()
                color = str(data.get("color", "")).strip()
                if not name or not (color.startswith("#") and len(color) == 7):
                    self._send_json({"ok": False, "error": "invalid input"}, 400)
                    return
                if not DB_PATH.exists():
                    self._send_json({"ok": False, "error": "calendar database not found"}, 404)
                    return
                with sqlite3.connect(str(DB_PATH), timeout=2.0) as c:
                    c.execute(
                        "INSERT OR REPLACE INTO calendar_colors VALUES (?,?)", (name, color)
                    )
                try:
                    ui_bus.command.emit("refresh", "calendar", "", "")
                except Exception as e:
                    print(f"[WebConfig] emit failed: {e}")
                self._send_json({"ok": True})

            elif path == "/api/install/status":
                self._send_json(_install_status())

            elif path == "/api/env":
                env_path = _ROOT / "variables.env"
                lines = [f"{k.strip()}={v.strip()}"
                         for k, v in data.items() if str(k).strip()]
                env_path.write_text("\n".join(lines) + "\n")
                self._send_json({"ok": True})

            elif path == "/api/install":
                script = data.get("script", "")
                allowed = {"install_ai.sh", "install_shairport.sh"}
                if script not in allowed:
                    self._send_json({"ok": False, "error": "unknown script"}, 400)
                    return
                result = _run_install(script)
                self._send_json({"ok": True, "status": result})

            elif path in ("/api/lights", "/api/plugs"):
                action     = str(data.get("action", "")).strip()
                name       = str(data.get("name",   "")).strip().lower()
                system     = str(data.get("system", "")).strip().lower()
                native_id  = str(data.get("native_id", "")).strip()
                is_lights  = path == "/api/lights"
                try:
                    if is_lights:
                        from ui_backend.light_backend import get_registry
                    else:
                        from ui_backend.plug_backend  import get_registry
                    reg = get_registry()
                    if action == "delete":
                        ok = reg.remove(name)
                        self._send_json({"ok": ok})
                    elif action == "add":
                        if not name or not system or not native_id:
                            self._send_json({"ok": False, "error": "name, system, and native_id required"}, 400)
                            return
                        reg.add(name, system, native_id)
                        self._send_json({"ok": True})
                    elif action == "discover_hue" and is_lights:
                        from ui_backend.light_backend import discover_hue
                        added = discover_hue()
                        self._send_json({"ok": True, "added": [l.name for l in added]})
                    else:
                        self._send_json({"ok": False, "error": f"unknown action {action!r}"}, 400)
                except Exception as e:
                    self._send_json({"ok": False, "error": str(e)}, 500)

            else:
                self._send_json({"error": "not found"}, 404)

        except Exception as e:
            try:
                self._send_json({"ok": False, "error": str(e)}, 500)
            except Exception:
                pass


# ── Threaded HTTP server ──────────────────────────────────────────────────────

class _Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads      = True   # worker threads die with the main process
    allow_reuse_address = True   # don't get "address already in use" on restart


# ── Public entry point ────────────────────────────────────────────────────────

# ── Install helpers ───────────────────────────────────────────────────────────
_install_procs: dict[str, subprocess.Popen] = {}

def _install_status() -> dict:
    statuses = {}
    for name, proc in list(_install_procs.items()):
        code = proc.poll()
        if code is None:
            statuses[name] = "running"
        elif code == 0:
            statuses[name] = "done"
        else:
            statuses[name] = f"failed (exit {code})"
    # ai.stt is imported by main.py before server starts; if it succeeded
    # the module is in sys.modules. Re-importing RealtimeSTT directly is
    # unreliable (CUDA side-effects, package name variations, etc.)
    statuses["ai_available"] = "ai.stt" in sys.modules
    statuses["shairport_available"] = bool(
        subprocess.run(["which", "shairport-sync"],
                       capture_output=True).returncode == 0)
    return statuses

def _run_install(script_name: str) -> str:
    script = _ROOT / script_name
    if not script.exists():
        return f"Script {script_name} not found"
    if script_name in _install_procs:
        if _install_procs[script_name].poll() is None:
            return "already running"
    log_path = _ROOT / f".{script_name}.log"
    proc = subprocess.Popen(
        ["bash", str(script)],
        stdout=open(log_path, "w"),
        stderr=subprocess.STDOUT,
        env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"},
    )
    _install_procs[script_name] = proc
    return "started"


def _local_ip() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        except Exception:
            return "localhost"


def start(host: str = "0.0.0.0", port: int = 80) -> None:
    # Try port 80 first so the URL needs no port number (http://wheatly.local).
    # Falls back automatically if 80 is blocked or busy.
    import sys as _sys
    for p in (80, 8080, 8888, 5001, 5002):
        try:
            srv = _Server((host, p), _Handler)
            port = p
            break
        except PermissionError:
            if p == 80:
                import os as _os
                real = _os.path.realpath(_sys.executable)
                print("[WebConfig] port 80 needs permission — run once to fix:")
                print(f"[WebConfig]   sudo setcap 'cap_net_bind_service=+ep' {real}")
            continue
        except OSError:
            continue
    else:
        print("[WebConfig] could not find a free port — web config disabled")
        return

    t = threading.Thread(target=srv.serve_forever, daemon=True, name="web-config")
    t.start()

    hostname = socket.gethostname()
    ip       = _local_ip()
    port_str = f":{port}" if port != 80 else ""
    print(f"[WebConfig] config page: http://{hostname}.local{port_str}  —  http://{ip}{port_str}")
