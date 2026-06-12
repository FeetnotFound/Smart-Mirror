"""Web config server — runs in a background daemon thread alongside the Qt app.

Uses Python's built-in http.server (no Flask) to avoid threading conflicts with
the Qt event loop. Binds to port 80 (requires cap_net_bind_service on the
Python binary) with automatic fallback to 8080, 8888, 5001, 5002.
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

# ui_bus is only available when running inside the Qt mirror app.
# When the web server runs as a standalone service (no display), the import
# is skipped and settings changes are written to disk only — the mirror app
# picks them up on next start.
try:
    from ui_backend.ui_control_backend import ui_bus as _ui_bus
except Exception:
    _ui_bus = None  # type: ignore

def _emit(cmd: str, a: str = "", b: str = "", c: str = "") -> None:
    if _ui_bus is not None:
        _ui_bus.command.emit(cmd, a, b, c)

_ROOT         = Path(__file__).resolve().parent.parent
_PROJECT_ROOT = _ROOT          # alias used by update handlers
SETTINGS_PATH = _ROOT / "settings.json"
STATIC_PATH   = Path(__file__).resolve().parent / "static"
DB_PATH       = _ROOT / "ui_backend" / "data" / "calendar.db"

_DEFAULTS: dict = {
    "mirror_name": "MIRROR",
    "calendar_days": 7,
    "tts_enabled":  True,
    "stt_enabled":  True,
    "alsa_device":  "",
    "alarm_volume": 0.5,
    "alarm_sound":  "",
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
    "schedule": {
        "enabled":      False,
        "sleep_time":   "23:00",
        "wake_time":    "07:00",
        "wakeup_sound": True,
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

            elif path == "/api/env":           self._get_env()
            elif path == "/api/models":        self._get_models()
            elif path == "/api/lights":        self._get_lights()
            elif path == "/api/plugs":         self._get_plugs()
            elif path == "/api/update/check":  self._get_update_check()
            elif path == "/api/timers":        self._get_timers()
            elif path == "/api/alarms":        self._get_alarms()
            elif path == "/api/alerts/active": self._get_alert_active()
            elif path == "/api/sounds":        self._get_sounds()
            elif path == "/api/light-groups":  self._get_light_groups()
            elif path == "/api/lights/control": self._send_json({"error": "POST only"}, 405)
            elif path == "/api/plugs/control":  self._send_json({"error": "POST only"}, 405)

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
                    result[k.strip()] = bool(v.strip())  # True = set, never expose value
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

    def _control_light(self, data: dict):
        name   = str(data.get("name",   "all")).strip()
        action = str(data.get("action", "on")).strip()
        brightness = data.get("brightness")
        color      = data.get("color") or None
        try:
            brightness = int(brightness) if brightness is not None else None
        except (TypeError, ValueError):
            brightness = None
        try:
            from ui_backend.light_backend import control_light
            msg = control_light(action, name, brightness, color)
            self._send_json({"ok": True, "message": msg})
        except Exception as e:
            self._send_json({"ok": False, "error": str(e)}, 500)

    def _control_plug(self, data: dict):
        name   = str(data.get("name",   "all")).strip()
        action = str(data.get("action", "on")).strip()
        try:
            from ui_backend.plug_backend import control_plug
            msg = control_plug(action, name)
            self._send_json({"ok": True, "message": msg})
        except Exception as e:
            self._send_json({"ok": False, "error": str(e)}, 500)

    def _get_light_groups(self):
        try:
            from ui_backend.light_backend import get_group_registry
            groups = [{"name": g.name, "members": g.members}
                      for g in get_group_registry().list()]
            self._send_json(groups)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _post_light_group(self, data: dict):
        action = str(data.get("action", "")).strip()
        name   = str(data.get("name",   "")).strip().lower()
        try:
            from ui_backend.light_backend import get_group_registry
            reg = get_group_registry()
            if action == "delete":
                self._send_json({"ok": reg.remove(name)})
            elif action == "add":
                members = data.get("members", [])
                if not isinstance(members, list) or not members:
                    self._send_json({"ok": False,
                                     "error": "members must be a non-empty list"}, 400)
                    return
                if not name:
                    self._send_json({"ok": False, "error": "name required"}, 400)
                    return
                reg.add(name, members)
                self._send_json({"ok": True})
            else:
                self._send_json({"ok": False,
                                 "error": f"unknown action {action!r}"}, 400)
        except Exception as e:
            self._send_json({"ok": False, "error": str(e)}, 500)

    def _get_timers(self):
        try:
            from ui_backend.timer_backend import get_manager
            timers = [
                {"id": t.id, "label": t.label,
                 "remaining": t.remaining, "total_seconds": t.total_seconds}
                for t in get_manager().active()
            ]
            self._send_json(timers)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _post_timer(self, data: dict):
        duration = str(data.get("duration", "")).strip()
        label    = str(data.get("label",    "")).strip()
        if not duration:
            self._send_json({"ok": False, "error": "duration required"}, 400)
            return
        try:
            from ui_backend.timer_backend import get_manager, parse_duration
            secs = parse_duration(duration)
            t = get_manager().set_timer(duration, label)
            mins, s = divmod(t.total_seconds, 60)
            human = f"{mins}m {s}s" if mins else f"{s}s"
            self._send_json({"ok": True, "id": t.id, "human": human})
        except ValueError as e:
            self._send_json({"ok": False, "error": str(e)}, 400)
        except Exception as e:
            self._send_json({"ok": False, "error": str(e)}, 500)

    def _cancel_timer(self, data: dict):
        try:
            from ui_backend.timer_backend import get_manager
            ok = get_manager().cancel(int(data.get("id", 0)))
            self._send_json({"ok": ok})
        except Exception as e:
            self._send_json({"ok": False, "error": str(e)}, 500)

    def _get_alarms(self):
        try:
            from ui_backend.alarm_backend import get_manager
            alarms = [
                {"id": a.id, "label": a.label, "target_iso": a.target_iso,
                 "repeat_daily": a.repeat_daily}
                for a in get_manager().active()
            ]
            self._send_json(alarms)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _get_sounds(self):
        from ui_backend.audio_backend import list_sounds
        selected = _load_settings().get("alarm_sound", "")
        self._send_json({"files": list_sounds(), "selected": selected})

    def _get_alert_active(self):
        try:
            from ui_backend.audio_backend import is_alert_active
            self._send_json({"active": is_alert_active()})
        except Exception as e:
            self._send_json({"active": False})

    def _post_alarm(self, data: dict):
        time_str     = str(data.get("time",  "")).strip()
        label        = str(data.get("label", "")).strip()
        repeat_daily = bool(data.get("repeat_daily", False))
        if not time_str:
            self._send_json({"ok": False, "error": "time required"}, 400)
            return
        try:
            from ui_backend.alarm_backend import get_manager
            a = get_manager().set_alarm(time_str, label, repeat_daily=repeat_daily)
            human = a.target.strftime("%-I:%M %p")
            self._send_json({"ok": True, "id": a.id, "human": human,
                             "repeat_daily": repeat_daily})
        except ValueError as e:
            self._send_json({"ok": False, "error": str(e)}, 400)
        except Exception as e:
            self._send_json({"ok": False, "error": str(e)}, 500)

    def _cancel_alarm(self, data: dict):
        try:
            from ui_backend.alarm_backend import get_manager
            ok = get_manager().cancel(int(data.get("id", 0)))
            self._send_json({"ok": ok})
        except Exception as e:
            self._send_json({"ok": False, "error": str(e)}, 500)

    def _dismiss_alert(self):
        try:
            from ui_backend.audio_backend import stop_alert
            stop_alert()
            self._send_json({"ok": True})
        except Exception as e:
            self._send_json({"ok": False, "error": str(e)}, 500)

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
                    if "tts_enabled" in data:
                        current["tts_enabled"] = bool(data["tts_enabled"])
                    if "alsa_device" in data:
                        current["alsa_device"] = str(data["alsa_device"]).strip()[:64]
                    if "alarm_volume" in data:
                        v = float(data["alarm_volume"])
                        current["alarm_volume"] = round(max(0.0, min(1.0, v)), 2)
                    if "alarm_sound" in data:
                        current["alarm_sound"] = str(data["alarm_sound"]).strip()[:128]
                    if "stt_enabled" in data:
                        enabled = bool(data["stt_enabled"])
                        current["stt_enabled"] = enabled
                        _emit("stt_start" if enabled else "stt_stop")
                    if "widgets" in data:
                        for name, visible in data["widgets"].items():
                            if name in current["widgets"]:
                                current["widgets"][name] = bool(visible)
                                _emit("show" if visible else "hide", name)
                    if "schedule" in data and isinstance(data["schedule"], dict):
                        sch = data["schedule"]
                        cur_sch = current.setdefault("schedule", {})
                        if "enabled" in sch:
                            cur_sch["enabled"] = bool(sch["enabled"])
                        if "sleep_time" in sch:
                            cur_sch["sleep_time"] = str(sch["sleep_time"])[:5]
                        if "wake_time" in sch:
                            cur_sch["wake_time"] = str(sch["wake_time"])[:5]
                        if "wakeup_sound" in sch:
                            cur_sch["wakeup_sound"] = bool(sch["wakeup_sound"])
                    save_settings(current)
                _emit("reload")
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
                _emit("refresh", "calendar")
                self._send_json({"ok": True})

            elif path == "/api/timers":          self._post_timer(data)
            elif path == "/api/timers/cancel":   self._cancel_timer(data)
            elif path == "/api/alarms":          self._post_alarm(data)
            elif path == "/api/alarms/cancel":   self._cancel_alarm(data)
            elif path == "/api/alerts/dismiss":  self._dismiss_alert()
            elif path == "/api/light-groups":       self._post_light_group(data)
            elif path == "/api/lights/control":     self._control_light(data)
            elif path == "/api/plugs/control":      self._control_plug(data)

            elif path == "/api/install/status":
                self._send_json(_install_status())

            elif path == "/api/env":
                env_path = _ROOT / "variables.env"
                # Read existing values so blank submissions preserve them
                existing: dict[str, str] = {}
                if env_path.exists():
                    for line in env_path.read_text().splitlines():
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            ek, _, ev = line.partition("=")
                            existing[ek.strip()] = ev.strip()
                # Only overwrite keys where a non-empty new value was submitted
                for k, v in data.items():
                    if str(k).strip() and str(v).strip():
                        existing[k.strip()] = str(v).strip()
                env_path.write_text(
                    "\n".join(f"{k}={v}" for k, v in existing.items()) + "\n"
                )
                self._send_json({"ok": True})

            elif path == "/api/update/apply":
                self._post_update_apply()

            elif path == "/api/install":
                script = data.get("script", "")
                allowed = {"install_ai.sh", "install_voice.sh", "install_shairport.sh"}
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

    # ── Update handlers ───────────────────────────────────────────────────────

    def _get_update_check(self):
        import urllib.request as _ur
        repo = "FeetnotFound/Smart-Mirror"
        try:
            current_sha = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=_PROJECT_ROOT, stderr=subprocess.DEVNULL
            ).decode().strip()
        except Exception:
            current_sha = "unknown"

        try:
            req = _ur.Request(
                f"https://api.github.com/repos/{repo}/commits/main",
                headers={"User-Agent": "mirror-os", "Accept": "application/vnd.github.v3+json"}
            )
            with _ur.urlopen(req, timeout=6) as r:
                data = json.loads(r.read())
            latest_sha = data["sha"]
            latest_msg = data["commit"]["message"].split("\n")[0][:80]
            up_to_date = current_sha == latest_sha
            self._send_json({
                "current": current_sha[:7],
                "latest":  latest_sha[:7],
                "up_to_date": up_to_date,
                "latest_message": latest_msg,
            })
        except Exception as e:
            self._send_json({
                "current": current_sha[:7] if current_sha != "unknown" else "unknown",
                "latest":  None,
                "up_to_date": None,
                "error": str(e),
            })

    def _post_update_apply(self):
        # Send the response immediately — the update runs in the background
        # and the mirror process exits via SIGTERM once done.
        # Sending from a background thread after the handler returns causes
        # a broken-pipe / "failed to fetch" on the client side.
        self._send_json({"ok": True, "output": "Updating — mirror will restart in about 30 seconds."})

        def _do_update():
            import time, signal
            try:
                subprocess.run(
                    ["git", "pull", "origin", "main"],
                    cwd=_PROJECT_ROOT, capture_output=True, text=True, timeout=60
                )
                subprocess.run(
                    [str(_PROJECT_ROOT / ".mirror" / "bin" / "pip"),
                     "install", "-q", "-r",
                     str(_PROJECT_ROOT / "requirements-base.txt")],
                    capture_output=True, text=True, timeout=180
                )
            except Exception:
                pass
            time.sleep(2)
            os.kill(os.getpid(), signal.SIGTERM)

        threading.Thread(target=_do_update, daemon=True).start()


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
    import importlib.util
    _s = load_settings()
    statuses["voice_available"]  = importlib.util.find_spec("RealtimeSTT") is not None
    statuses["piper_available"]  = importlib.util.find_spec("piper") is not None
    statuses["tts_enabled"]      = _s.get("tts_enabled", True)
    statuses["stt_enabled"]      = _s.get("stt_enabled", True)
    try:
        import urllib.request as _ur
        with _ur.urlopen("http://localhost:11434/api/tags", timeout=2) as r:
            statuses["ai_available"] = r.status == 200
    except Exception:
        statuses["ai_available"] = False
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
    import getpass
    current_user = getpass.getuser()
    def _run():
        proc = subprocess.Popen(
            ["bash", str(script)],
            stdout=open(log_path, "w"),
            stderr=subprocess.STDOUT,
            env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"},
        )
        _install_procs[script_name] = proc
        proc.wait()
        # Fix any root-owned files left by pip/apt running under sudo
        subprocess.run(
            ["sudo", "chown", "-R", f"{current_user}:{current_user}", str(_ROOT)],
            capture_output=True,
        )
    import threading
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    # Give the thread a moment to set _install_procs before returning
    import time; time.sleep(0.2)
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


if __name__ == "__main__":
    # Standalone mode — runs the web config server without the Qt mirror app.
    # Settings changes are written to disk; the mirror app picks them up on restart.
    # The server blocks here (no daemon thread) so systemd can manage the process.
    import sys as _sys
    for p in (80, 8080, 8888, 5001, 5002):
        try:
            srv = _Server(("0.0.0.0", p), _Handler)
            break
        except (PermissionError, OSError):
            continue
    else:
        print("[WebConfig] no free port found — exiting")
        _sys.exit(1)

    hostname = socket.gethostname()
    ip       = _local_ip()
    port_str = f":{p}" if p != 80 else ""
    print(f"[WebConfig] standalone: http://{hostname}.local{port_str}  —  http://{ip}{port_str}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
