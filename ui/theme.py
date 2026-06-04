"""Global UI text colors — updated from settings.json before each UI rebuild."""

text  = "#dddddd"   # primary content (event titles, task text, main labels)
mid   = "#888888"   # secondary (dates, subtitles, clock date)
dim   = "#444444"   # headers ("CALENDAR", "TASKS", etc.) and dimmed labels


def apply(colors: dict) -> None:
    global text, mid, dim
    text = colors.get("text", "#dddddd")
    mid  = colors.get("mid",  "#888888")
    dim  = colors.get("dim",  "#444444")
