"""UI control backend — show/hide/move widgets by voice.

Router signature:  control_user_interface(action, module, location, size)

This one is different: it doesn't do work, it tells the UI to rearrange itself.
Because the router runs on a worker thread and Qt widgets must only be touched
on the main thread, this emits a Qt signal that the main window connects to.
Import the singleton bus and connect to it in main.py:

    from ui_backend.ui_control_backend import ui_bus
    ui_bus.command.connect(window.handle_ui_command)
"""
from PySide6.QtCore import QObject, Signal


class _UIBus(QObject):
    # action, module, location, size  — all strings, location/size may be ""
    command = Signal(str, str, str, str)


ui_bus = _UIBus()


def control_user_interface(action: str, module: str,
                           location: str = "", size: str = "") -> str:
    ui_bus.command.emit(action, module, location or "", size or "")
    verb = {"show": "Showing", "hide": "Hiding", "move": "Moving"}.get(action, "Updating")
    return f"{verb} {module}."
