"""On-screen terminal module for the mirror UI.

Contains:
  • ansi_to_html  — convert ANSI-coloured log lines to HTML spans
  • LogStream     — a file-like stdout replacement that streams lines to Qt
  • Terminal      — a read-only, square, shell-styled log widget

main.py wires these together:
    term = Terminal()
    stream = LogStream(tee=sys.__stdout__)
    stream.line.connect(term.append_line)
    sys.stdout = stream
"""

import re
import threading

from PySide6.QtWidgets import QPlainTextEdit
from PySide6.QtCore    import Qt, Signal, QObject
from PySide6.QtGui     import QFont, QTextBlockFormat, QTextCursor


# ── [Tag] colorizer ──────────────────────────────────────────────────────────

_TAG_COLORS: dict[str, str] = {
    "calendar": "#57c7ff",   # blue      – scheduling
    "ear":      "#5af78e",   # green     – STT / listening
    "tts":      "#ff6ac1",   # pink      – speech output
    "timer":    "#f3f99d",   # yellow    – countdown
    "alarm":    "#ff6e67",   # red       – alert
    "task":     "#9aedfe",   # cyan      – task list
    "light":    "#ffe080",   # gold      – lights
    "plug":     "#b8f09a",   # lime      – smart plugs
    "music":    "#cf9fff",   # lavender  – AirPlay / shairport
    "ui":       "#8a8a8a",   # grey      – ui control
    "ollama":   "#d4c5f9",   # violet    – LLM responses
    "llm":      "#d4c5f9",
    "system":   "#6c6c6c",   # dark grey – system info
    "weather":  "#57c7ff",
    "search":   "#9aedfe",
}

# Matches [Tag] and captures everything after it on the same line
_TAG_RE = re.compile(r'\[([A-Za-z][A-Za-z0-9_\- ]*)\](.*)')


def _dim(hex_color: str, factor: float = 0.55) -> str:
    """Return a darkened version of a hex color (blend toward black)."""
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)
    return "#{:02x}{:02x}{:02x}".format(
        int(r * factor), int(g * factor), int(b * factor))


def _colorize_tags(html: str) -> str:
    """Color [Tag] bold+bright and the rest of the line in a dimmer shade."""
    def _sub(m: re.Match) -> str:
        name  = m.group(1)
        rest  = m.group(2)
        color = _TAG_COLORS.get(name.lower(), "#888888")
        dim   = _dim(color)
        tag_html = (f'<span style="color:{color};font-weight:bold;">'
                    f'[{name}]</span>')
        msg_html = (f'<span style="color:{dim};">{rest}</span>') if rest else ""
        return tag_html + msg_html
    return _TAG_RE.sub(_sub, html)


# ── ANSI → HTML ───────────────────────────────────────────────────────────────

_ANSI_RE = re.compile(r"\x1b\[([0-9;]*)m")

# ANSI SGR code → on-black hex colour (mirrors config.py's scheme)
_ANSI_COLORS = {
    "30": "#6c6c6c", "31": "#ff6e67", "32": "#5af78e", "33": "#f3f99d",
    "34": "#57c7ff", "35": "#ff6ac1", "36": "#9aedfe", "37": "#f1f1f0",
    "90": "#8a8a8a", "91": "#ff6e67", "92": "#5af78e", "93": "#f3f99d",
    "94": "#57c7ff", "95": "#ff6ac1", "96": "#9aedfe", "97": "#ffffff",
}


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def ansi_to_html(line: str) -> str:
    """Convert a line containing ANSI SGR colour codes into HTML spans."""
    parts = _ANSI_RE.split(line)          # [text, codes, text, codes, ...]
    color = None
    bold  = False
    out   = []
    for i, seg in enumerate(parts):
        if i % 2 == 0:                    # text segment
            if not seg:
                continue
            style = ""
            if color:
                style += f"color:{color};"
            if bold:
                style += "font-weight:bold;"
            out.append(f'<span style="{style}">{_esc(seg)}</span>' if style else _esc(seg))
        else:                             # SGR code segment
            for code in (seg.split(";") if seg else ["0"]):
                if code in ("", "0"):
                    color, bold = None, False
                elif code == "1":
                    bold = True
                elif code in _ANSI_COLORS:
                    color = _ANSI_COLORS[code]
    return "".join(out)


# ── stdout → Qt bridge ────────────────────────────────────────────────────────

class LogStream(QObject):
    """File-like object that tees writes to the real stdout and emits each
    completed line as a Qt signal so the GUI thread can render it.

    write() is called from multiple worker threads (STT, TTS producer, the
    preload threads), so the line buffer is guarded by a lock. The emitted
    signal is delivered to the GUI thread via a queued connection.
    """

    line = Signal(str)

    def __init__(self, tee=None) -> None:
        super().__init__()
        self._tee  = tee
        self._buf  = ""
        self._lock = threading.Lock()

    def write(self, s: str) -> int:
        if self._tee:
            self._tee.write(s)
        with self._lock:
            self._buf += s
            while "\n" in self._buf:
                ln, self._buf = self._buf.split("\n", 1)
                self.line.emit(ln)
        return len(s)

    def flush(self) -> None:
        if self._tee:
            self._tee.flush()

    def fileno(self) -> int:
        return self._tee.fileno() if self._tee else 1


# ── Terminal widget ───────────────────────────────────────────────────────────

class Terminal(QPlainTextEdit):
    """A read-only, square, scroll-pinned log view styled like a shell."""

    # Apple's monospace terminal font, with graceful fallbacks for non-mac
    # hosts (e.g. a Raspberry Pi, where SF Mono / Menlo are not installed).
    _FONT_STACK = ["SF Mono", "Menlo", "Monaco", "DejaVu Sans Mono"]

    def __init__(self, size: int = 440, point_size: int = 11,
                 line_spacing: float = 1.6) -> None:
        super().__init__()
        self._line_spacing = line_spacing      # proportional line height (1.0 = normal)
        self.setReadOnly(True)
        self.setMaximumBlockCount(1000)        # ring buffer; oldest lines drop off
        self.setFixedSize(size, size)
        sp = self.sizePolicy(); sp.setRetainSizeWhenHidden(True); self.setSizePolicy(sp)
        self.setFrameStyle(0)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)

        font = QFont()
        font.setFamilies(self._FONT_STACK)
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(point_size)
        self.setFont(font)

        self.setStyleSheet(
            "QPlainTextEdit {"
            "  background-color: #0a0a0a;"
            "  color: #cccccc;"
            "  border: 1px solid #222222;"
            "  border-radius: 6px;"
            "  padding: 10px;"
            "}"
        )

    def append_line(self, raw: str) -> None:
        self.appendHtml(_colorize_tags(ansi_to_html(raw)))

        # QPlainTextEdit ignores CSS line-height, so set spacing on the block
        # we just added via a proportional line height (percent).
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        block_fmt = QTextBlockFormat()
        block_fmt.setLineHeight(
            self._line_spacing * 100,
            QTextBlockFormat.LineHeightTypes.ProportionalHeight.value,
        )
        cursor.mergeBlockFormat(block_fmt)

        sb = self.verticalScrollBar()
        sb.setValue(sb.maximum())              # stay pinned to the newest line