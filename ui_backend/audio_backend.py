"""Audio playback for alarms, timers, and wake-up events.

Generates simple WAV tones on first use (no pre-baked binary files needed).
Plays via aplay (alsa-utils). Falls back through paplay → ffplay silently if
aplay isn't available.
"""
import math
import struct
import subprocess
import threading
import wave
from pathlib import Path

SOUNDS_DIR = Path(__file__).resolve().parent.parent / "sounds"
_SAMPLE_RATE = 44100


def _make_tone(path: Path, freq: float, duration: float, repeats: int = 1,
               gap: float = 0.15, volume: float = 0.7) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    spb = int(_SAMPLE_RATE * duration)   # samples per beep
    spg = int(_SAMPLE_RATE * gap)        # samples per gap

    data: list[int] = []
    for i in range(repeats):
        for n in range(spb):
            t = n / _SAMPLE_RATE
            # linear fade-out in last 10 % of each beep
            env = 1.0 - max(0.0, (n - spb * 0.9)) / (spb * 0.1 + 1)
            data.append(int(volume * 32767 * math.sin(2 * math.pi * freq * t) * env))
        if i < repeats - 1:
            data.extend([0] * spg)

    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(_SAMPLE_RATE)
        wf.writeframes(struct.pack(f"<{len(data)}h", *data))


def _ensure_sounds() -> None:
    SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
    if not (SOUNDS_DIR / "alarm.wav").exists():
        # Three sharp 880 Hz beeps — urgent
        _make_tone(SOUNDS_DIR / "alarm.wav", freq=880, duration=0.25,
                   repeats=3, gap=0.08)
    if not (SOUNDS_DIR / "timer.wav").exists():
        # Two mellow 660 Hz chimes
        _make_tone(SOUNDS_DIR / "timer.wav", freq=660, duration=0.45,
                   repeats=2, gap=0.20)
    if not (SOUNDS_DIR / "wakeup.wav").exists():
        # Three gentle ascending notes
        _make_tone(SOUNDS_DIR / "wakeup.wav", freq=440, duration=0.35,
                   repeats=3, gap=0.30, volume=0.5)


def play(filename: str) -> None:
    """Play a sound from sounds/. Non-blocking; fails silently if no player found."""
    def _do():
        try:
            _ensure_sounds()
        except Exception:
            return
        path = SOUNDS_DIR / filename
        if not path.exists():
            return
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

    threading.Thread(target=_do, daemon=True).start()
