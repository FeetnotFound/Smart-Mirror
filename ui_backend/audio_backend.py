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
    """Two-tone repeating klaxon: 3× (400 Hz / 800 Hz) pairs + trailing silence."""
    data: list[int] = []
    for _ in range(3):
        for freq in (400, 800):
            dur = int(_SAMPLE_RATE * 0.18)
            for n in range(dur):
                t = n / _SAMPLE_RATE
                env = 1.0 - max(0.0, (n - dur * 0.88)) / (dur * 0.12 + 1)
                data.append(int(0.8 * 32767 * math.sin(2 * math.pi * freq * t) * env))
        data.extend([0] * int(_SAMPLE_RATE * 0.12))
    data.extend([0] * int(_SAMPLE_RATE * 0.5))
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


def _ensure_sounds() -> None:
    SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
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
        tts = SOUNDS_DIR / "wakeup_tts.wav"
        if not tts.exists():
            _try_generate_tts("Good morning! Your alarm is going off.", tts)
        return tts if tts.exists() else SOUNDS_DIR / "wakeup_chime.wav"
    return SOUNDS_DIR / "klaxon.wav"


def _try_generate_tts(text: str, out: Path) -> None:
    """Generate a WAV via piper if a model is installed — silently skips if not."""
    try:
        import importlib.util
        if importlib.util.find_spec("piper") is None:
            return
        from piper import PiperVoice
        import wave as _wave

        search_dirs = [
            Path(__file__).resolve().parent.parent / "models" / "voice_models",
            Path.home() / ".local" / "share" / "piper",
        ]
        model_path: Path | None = None
        for d in search_dirs:
            if d.exists():
                found = list(d.glob("*.onnx"))
                if found:
                    model_path = found[0]
                    break
        if model_path is None:
            return

        voice = PiperVoice.load(str(model_path))
        out.parent.mkdir(parents=True, exist_ok=True)
        with _wave.open(str(out), "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(voice.config.sample_rate)
            for chunk in voice.synthesize_stream_raw(text):
                wf.writeframes(chunk)
    except Exception:
        pass


def stop_alert() -> None:
    """Stop any looping alert immediately."""
    _alert_stop.set()


def is_alert_active() -> bool:
    """True while a looping alert is running."""
    return not _alert_stop.is_set()
