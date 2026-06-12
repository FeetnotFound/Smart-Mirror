"""Audio playback for alarms, timers, and wake-up events.

Generates WAV tones on first use (no pre-baked binary files needed).
Plays via aplay (alsa-utils) with fallbacks.

Alert API
─────────
  play_alert("alarm" | "timer" | "wakeup")  — start looping until stop_alert()
  stop_alert()                               — stop the looping alert
  is_alert_active()                          — True while looping
  play(filename)                             — one-shot, non-blocking
"""
import math
import struct
import subprocess
import threading
import wave
from pathlib import Path

SOUNDS_DIR = Path(__file__).resolve().parent.parent / "sounds"
_SAMPLE_RATE = 44100

# ── Alert state ───────────────────────────────────────────────────────────────
_alert_stop = threading.Event()
_alert_stop.set()   # not active at startup


# ── Sound generation ──────────────────────────────────────────────────────────

def _write_wav(path: Path, data: list[int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(_SAMPLE_RATE)
        wf.writeframes(struct.pack(f"<{len(data)}h", *data))


def _make_tone(path: Path, freq: float, duration: float, repeats: int = 1,
               gap: float = 0.15, volume: float = 0.7) -> None:
    spb = int(_SAMPLE_RATE * duration)
    spg = int(_SAMPLE_RATE * gap)
    data: list[int] = []
    for i in range(repeats):
        for n in range(spb):
            t = n / _SAMPLE_RATE
            env = 1.0 - max(0.0, (n - spb * 0.9)) / (spb * 0.1 + 1)
            data.append(int(volume * 32767 * math.sin(2 * math.pi * freq * t) * env))
        if i < repeats - 1:
            data.extend([0] * spg)
    _write_wav(path, data)


def _make_klaxon(path: Path) -> None:
    """Star Wars Imperial klaxon: sawtooth two-tone alarm, 4 pairs + trailing silence."""
    SR = _SAMPLE_RATE
    data: list[int] = []
    vol = 0.70

    def _saw(freq: float, t: float) -> float:
        # Sawtooth Fourier series — harsh, metallic quality
        s = 0.0
        for h in range(1, 9):
            s += math.sin(2 * math.pi * freq * h * t) * ((-1) ** (h + 1)) / h
        return s * (2 / math.pi)

    for _ in range(4):
        for freq in (880, 440):
            dur = int(SR * 0.13)
            for n in range(dur):
                t = n / SR
                attack  = min(n / int(SR * 0.005 + 1), 1.0)
                release = 1.0 - max(0.0, (n - dur * 0.85)) / (dur * 0.15 + 1)
                sample  = _saw(freq, t) * vol * attack * release
                data.append(int(max(-32767, min(32767, sample * 32767))))
        data.extend([0] * int(SR * 0.04))  # brief gap between cycles

    data.extend([0] * int(SR * 0.4))  # silence before loop
    _write_wav(path, data)


def _make_wakeup_chime(path: Path) -> None:
    """Gentle ascending three-note chime (E4 → G#4 → C5)."""
    data: list[int] = []
    for freq in (330, 415, 523):
        dur = int(_SAMPLE_RATE * 0.5)
        for n in range(dur):
            t = n / _SAMPLE_RATE
            attack = min(n / (_SAMPLE_RATE * 0.04), 1.0)
            decay  = 1.0 - max(0.0, (n - dur * 0.65)) / (dur * 0.35 + 1)
            data.append(int(0.4 * 32767 * math.sin(2 * math.pi * freq * t) * attack * decay))
        data.extend([0] * int(_SAMPLE_RATE * 0.1))
    data.extend([0] * int(_SAMPLE_RATE * 1.5))
    _write_wav(path, data)


_SOUNDS_VERSION = 2   # bump to force regeneration of all sounds

def _ensure_sounds() -> None:
    SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
    ver_file = SOUNDS_DIR / ".version"
    current_ver = int(ver_file.read_text().strip()) if ver_file.exists() else 0
    if current_ver < _SOUNDS_VERSION:
        for f in SOUNDS_DIR.glob("*.wav"):
            f.unlink(missing_ok=True)
        ver_file.write_text(str(_SOUNDS_VERSION))

    if not (SOUNDS_DIR / "klaxon.wav").exists():
        _make_klaxon(SOUNDS_DIR / "klaxon.wav")
    if not (SOUNDS_DIR / "wakeup_chime.wav").exists():
        _make_wakeup_chime(SOUNDS_DIR / "wakeup_chime.wav")
    # Legacy names kept for any existing references
    if not (SOUNDS_DIR / "alarm.wav").exists():
        _make_klaxon(SOUNDS_DIR / "alarm.wav")
    if not (SOUNDS_DIR / "timer.wav").exists():
        _make_klaxon(SOUNDS_DIR / "timer.wav")
    if not (SOUNDS_DIR / "wakeup.wav").exists():
        _make_wakeup_chime(SOUNDS_DIR / "wakeup.wav")


# ── Playback helpers ──────────────────────────────────────────────────────────

def _aplay_once(path: Path) -> None:
    for cmd in (
        ["aplay", "-q", str(path)],
        ["paplay", str(path)],
        ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(path)],
    ):
        try:
            if subprocess.run(cmd, capture_output=True, timeout=30).returncode == 0:
                return
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue


def play(filename: str) -> None:
    """Play once, non-blocking. Fails silently if no player found."""
    def _do():
        try:
            _ensure_sounds()
        except Exception:
            return
        path = SOUNDS_DIR / filename
        if path.exists():
            _aplay_once(path)
    threading.Thread(target=_do, daemon=True).start()


# ── Looping alert ─────────────────────────────────────────────────────────────

def play_alert(kind: str) -> None:
    """Start looping alert. kind = 'alarm' | 'timer' | 'wakeup'. Stops on stop_alert()."""
    global _alert_stop
    _alert_stop.set()          # cancel any existing alert immediately
    stop_ev = threading.Event()
    _alert_stop = stop_ev

    def _loop() -> None:
        try:
            _ensure_sounds()
        except Exception:
            return
        wav = _pick_wav(kind)
        while not stop_ev.is_set():
            _aplay_once(wav)
            stop_ev.wait(0.4)

    threading.Thread(target=_loop, daemon=True).start()


def _pick_wav(kind: str) -> Path:
    if kind == "wakeup":
        return SOUNDS_DIR / "wakeup_chime.wav"
    # Alarm / timer: check for user-supplied custom file first.
    # Drop sounds/klaxon_custom.wav (or .mp3 / .ogg) to use your own sound.
    for ext in ("wav", "mp3", "ogg", "flac"):
        custom = SOUNDS_DIR / f"klaxon_custom.{ext}"
        if custom.exists():
            return custom
    return SOUNDS_DIR / "klaxon.wav"


def stop_alert() -> None:
    """Stop any looping alert immediately."""
    _alert_stop.set()


def is_alert_active() -> bool:
    """True while a looping alert is running."""
    return not _alert_stop.is_set()
