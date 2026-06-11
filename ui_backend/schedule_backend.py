"""Mirror display schedule — sleep window and wake-up.

Blanks the X11 display during configured sleep hours and restores it at the
wake time. X11 commands run via subprocess with DISPLAY=:0 so this works
whether called from the Qt app or the standalone web server.
"""
import os
import subprocess
from datetime import datetime, time as _time


def _xset(*args: str) -> None:
    env = {**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")}
    try:
        subprocess.run(["xset", *args], env=env, capture_output=True, timeout=5)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass


def blank_display() -> None:
    _xset("dpms", "force", "off")


def unblank_display() -> None:
    _xset("dpms", "force", "on")
    _xset("-dpms")          # re-disable auto-DPMS so normal operation continues


def _parse_hhmm(s: str) -> "_time | None":
    try:
        h, m = s.split(":")
        return _time(int(h), int(m))
    except Exception:
        return None


def in_sleep_window(sleep_str: str, wake_str: str) -> bool:
    """True if the current local time is inside [sleep_str, wake_str)."""
    st = _parse_hhmm(sleep_str)
    wt = _parse_hhmm(wake_str)
    if st is None or wt is None:
        return False
    now = datetime.now().time()
    if st == wt:
        return False
    if st < wt:
        # e.g. 01:00 – 06:00 (daytime nap window, unusual)
        return st <= now < wt
    else:
        # wraps midnight — sleep=23:00, wake=07:00
        return now >= st or now < wt
