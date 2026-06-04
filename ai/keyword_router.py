import re
from typing import Tuple, Any

from config import ROUTER, RESET, ts


# ── Argument extractors ────────────────────────────────────────────────────────
# Each function receives the lowercased raw text and returns a kwargs dict
# matching the corresponding backend's function signature exactly.

def _extract_timer(text: str) -> dict:
    """'set a timer for 5 minutes' -> {'duration': '5 minutes'}"""
    m = re.search(r"\bfor\s+(.+?)(?:\s+(?:starting|now|please))?$", text, re.I)
    if m:
        return {"duration": m.group(1).strip()}
    m = re.search(r"(\d+(?:\.\d+)?\s*(?:hour|hr|minute|min|second|sec)s?)", text, re.I)
    if m:
        return {"duration": m.group(0).strip()}
    return {"duration": text}


def _extract_alarm(text: str) -> dict:
    """'set alarm for 7:30 am' -> {'time': '7:30 am'}"""
    m = re.search(r"\b(?:for|at)\s+(.+?)(?:\s+(?:tomorrow|today|please))?$", text, re.I)
    if m:
        return {"time": m.group(1).strip()}
    m = re.search(r"\d{1,2}(?::\d{2})?\s*(?:am|pm)", text, re.I)
    if m:
        return {"time": m.group(0).strip()}
    return {"time": text}


def _extract_task(text: str) -> dict:
    """'remind me to buy milk' -> {'text': 'buy milk'}"""
    for pat in (
        r"remind me to\s+(.+)",
        r"(?:add|put)\s+(.+?)\s+(?:to\s+)?(?:my\s+)?(?:task|todo|to-do|list)s?$",
        r"(?:add|create)\s+(?:a\s+)?(?:task|todo|to-do)\s+(?:to\s+)?(.+)",
    ):
        m = re.search(pat, text, re.I)
        if m:
            return {"text": m.group(1).strip()}
    return {"text": text}


_LIGHT_SKIP = frozenset((
    "the", "a", "an", "my", "all", "turn", "switch", "on", "off",
    "please", "light", "lights", "lamp", "lamps", "bulb",
    "alarm", "timer", "plug", "outlet", "socket",  # prevent mis-extraction
))


def _extract_light(text: str) -> dict:
    """Extract action/device_name/brightness/color for control_light.

    Device name is pulled from the phrase rather than a hard-coded room list so
    any name in the registry works: 'turn on couch', 'couch light', etc.
    """
    off = bool(re.search(r"\b(?:off|turn off|disable|switch off)\b", text, re.I))
    action = "off" if off else "on"

    bri_m = re.search(r"\b(\d{1,3})\s*(?:percent|%|brightness)\b", text, re.I)
    brightness = int(bri_m.group(1)) if bri_m else None

    _COLORS = ("red", "green", "blue", "white", "warm", "cool",
               "yellow", "orange", "purple", "pink", "cyan")
    color = next((c for c in _COLORS if re.search(rf"\b{c}\b", text, re.I)), None)

    device_name = "all"

    # Pattern 1: "[device] light(s)/lamp/bulb" — device precedes the light noun
    noun_m = re.search(r"\b(\w+)\s+(?:lights?|lamp|bulb)\b", text, re.I)
    if noun_m and noun_m.group(1).lower() not in _LIGHT_SKIP:
        device_name = noun_m.group(1).lower()

    # Pattern 2: "turn/switch on/off [the] [device] [optional noun]"
    # Captures up to two words so "turn on the light couch" finds "couch" when
    # the first captured word ("light") is itself a light noun.
    if device_name == "all":
        phrase_m = re.search(
            r"\b(?:turn|switch)\s+(?:on|off)\s+(?:the\s+)?(\w+)(?:\s+(\w+))?",
            text, re.I)
        if phrase_m:
            w1 = phrase_m.group(1).lower()
            w2 = (phrase_m.group(2) or "").lower()
            if w1 not in _LIGHT_SKIP:
                device_name = w1
            elif w2 and w2 not in _LIGHT_SKIP:
                device_name = w2

    return {"action": action, "device_name": device_name,
            "brightness": brightness, "color": color}


def _extract_plug(text: str) -> dict:
    """'turn on the coffee maker plug' -> {'action': 'on', 'device_name': 'coffee maker'}"""
    off = bool(re.search(r"\b(?:off|turn off|disable|switch off|unplug)\b", text, re.I))
    action = "off" if off else "on"

    # Strip plug/outlet/socket from name extraction
    _PLUG_SKIP = frozenset(("the", "a", "an", "my", "all", "plug", "outlet",
                             "socket", "turn", "switch", "on", "off"))
    phrase_m = re.search(
        r"\b(?:turn|switch)\s+(?:on|off)\s+(?:the\s+)?(.+?)(?:\s+plug|\s+outlet|\s+socket)?$",
        text, re.I)
    if phrase_m:
        candidate = phrase_m.group(1).strip().lower()
        candidate = re.sub(r"\b(plug|outlet|socket|the|a|an)\b", "", candidate).strip()
        device_name = candidate if candidate else "all"
    else:
        device_name = "all"

    return {"action": action, "device_name": device_name}


def _extract_search(text: str) -> dict:
    """'search for best pizza' -> {'query': 'best pizza'}"""
    for pat in (
        r"(?:search for|google|look up|find|search)\s+(.+)",
        r"news (?:about|on)\s+(.+)",
        r"(?:latest|current)\s+(.+?)(?:\s+(?:news|headlines))?$",
    ):
        m = re.search(pat, text, re.I)
        if m:
            return {"query": m.group(1).strip()}
    return {"query": text}


def _extract_ui_control(text: str) -> dict:
    """'show calendar widget' -> {'action': 'show', 'module': 'calendar', 'location': ''}"""
    action_m = re.search(r"\b(show|display|open|hide|close|remove|move|resize)\b", text, re.I)
    raw_action = action_m.group(1).lower() if action_m else "show"
    action = {"display": "show", "open": "show",
               "close": "hide", "remove": "hide"}.get(raw_action, raw_action)

    module_m = re.search(
        r"\b(calendar|clock|timer|alarm|tasks?|todo|weather|terminal|system)\b",
        text, re.I)
    raw_module = module_m.group(1).lower() if module_m else ""
    module = {"todo": "tasks", "task": "tasks"}.get(raw_module, raw_module)

    location_m = re.search(r"\b(left|right|top|bottom|center)\b", text, re.I)
    location = location_m.group(1).lower() if location_m else ""

    return {"action": action, "module": module, "location": location}


def _extract_complete_task(text: str) -> dict:
    """'check off call my mom' -> {'text': 'call my mom'}"""
    for pat in (
        r"check off\s+(.+)",
        r"mark(?:\s+(?:as\s+)?)done\s+(.+)",
        r"(?:complete|finish|mark off)\s+(.+)",
    ):
        m = re.search(pat, text, re.I)
        if m:
            return {"text": m.group(1).strip()}
    return {"text": text}


def _raw(text: str) -> dict:
    """Pass-through for commands whose backends do their own NLP (e.g. calendar)."""
    return {"raw": text}


class KeywordRouter:
    """Near-zero-latency rule-based router. Drop-in for FunctionRouter.

    Returns (function_name, args_dict) where args_dict matches the target
    backend's function signature so executer can call handler(**args) directly.

    Accepts and ignores any constructor kwargs so it can be swapped in for
    FunctionRouter without touching the caller (e.g. model_path=...).
    """

    def __init__(self, **_: Any) -> None:
        pass

    # Ordered: first match wins.
    # control_user_interface is FIRST so "move/show/hide <module>" is caught
    # before any rule that also matches the module name (e.g. "move the timer"
    # would otherwise hit set_timer because "timer" appears in the text).
    _RULES: list[tuple[str, re.Pattern, Any]] = [
        ("control_user_interface", re.compile(
            r"\b(show|hide|display|open|close|move|resize)\b"
            r".*\b(widget|calendar|clock|timer|alarm|tasks?|terminal|system)\b"),
         _extract_ui_control),
        ("set_timer", re.compile(
            r"\b(set|start)\b.*\btimer\b|\btimer\b.*\bfor\b"),
         _extract_timer),
        ("set_alarm", re.compile(
            r"\b(set|wake me)\b.*\balarm\b|\balarm\b.*\bfor\b"),
         _extract_alarm),
        ("control_light", re.compile(
            r"\b(lights?|lamp|brightness|dim|bulb)\b"),
         _extract_light),
        # complete_task before add_task so "check off X" doesn't hit add_task
        ("complete_task", re.compile(
            r"\b(?:check off|mark(?:\s+(?:as\s+)?)?done|finish|mark off)\b"),
         _extract_complete_task),
        # add_task before create_calendar_event: "reminder" → task not calendar
        ("add_task", re.compile(
            r"\b(add|put)\b.*\b(task|todo|to-do|to do|list)\b|\bremind me to\b"),
         _extract_task),
        # "reminder" intentionally removed; only calendar-specific nouns remain
        ("create_calendar_event", re.compile(
            r"\b(schedule|add|create|book)\b.*\b(event|meeting|appointment)\b"),
         _raw),
        ("web_search", re.compile(
            r"\b(search|google|look up|latest|news|headlines)\b"),
         _extract_search),
        ("get_system_info", re.compile(
            r"\b(cpu|ram|memory|disk|system info|temperature|battery|uptime)\b"),
         lambda _: {}),
        # plug — explicit "plug/outlet/socket" keyword
        ("control_plug", re.compile(
            r"\b(plug|outlet|socket)\b"),
         _extract_plug),
        # catch-all: "turn on/off [device]" for anything not matched above.
        # MUST be last — earlier rules already handle alarms, timers, UI, etc.
        ("control_light", re.compile(
            r"\b(?:turn|switch)\s+(?:on|off)\b"),
         _extract_light),
    ]

    _THINK_RE = re.compile(
        r"\b(why|how come|explain|reason|compare|difference|"
        r"should i|pros and cons|walk me through|step by step|in detail)\b"
    )

    def route(self, user_input: str) -> Tuple[str, dict[str, Any]]:
        text = user_input.lower().strip()

        for name, pattern, extractor in self._RULES:
            if pattern.search(text):
                print(f"{ts()}{ROUTER}[Router] matched {name}{RESET}")
                return name, extractor(text)

        mode = "thinking" if self._THINK_RE.search(text) else "nonthinking"
        return mode, {"prompt": user_input}
