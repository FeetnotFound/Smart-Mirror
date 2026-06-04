"""Music backend — reads Now Playing from shairport-sync via MPRIS D-Bus.

Uses dbus-python (no PyGObject/gi required).
"""
from __future__ import annotations
from dataclasses import dataclass

_DBUS_NAME  = "org.mpris.MediaPlayer2.ShairportSync"
_DBUS_PATH  = "/org/mpris/MediaPlayer2"
_PROPS_IFACE = "org.freedesktop.DBus.Properties"
_PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"


@dataclass
class NowPlaying:
    title:   str  = ""
    artist:  str  = ""
    album:   str  = ""
    art_url: str  = ""
    playing: bool = False


def poll() -> NowPlaying:
    """Return current playback state. Never raises."""
    try:
        import dbus
        bus    = dbus.SystemBus()
        obj    = bus.get_object(_DBUS_NAME, _DBUS_PATH)
        props  = dbus.Interface(obj, _PROPS_IFACE)

        status = str(props.Get(_PLAYER_IFACE, "PlaybackStatus"))
        meta   = props.Get(_PLAYER_IFACE, "Metadata")

        def s(k):
            v = meta.get(k, "")
            return str(v) if v else ""

        def lst(k):
            v = meta.get(k, [])
            return ", ".join(str(x) for x in v) if v else ""

        return NowPlaying(
            title   = s("xesam:title"),
            artist  = lst("xesam:artist"),
            album   = s("xesam:album"),
            art_url = s("mpris:artUrl"),
            playing = (status == "Playing"),
        )
    except Exception:
        return NowPlaying()
