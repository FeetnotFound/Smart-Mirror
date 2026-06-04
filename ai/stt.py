import os
import sys
import re
import logging
from pathlib import Path
from typing import Callable, Optional

# ── Suppress noisy third-party output before heavy imports ───────────────────
# os.environ["PYTHONWARNINGS"] = "ignore"
# logging.getLogger("ctranslate2").setLevel(logging.ERROR)

# _devnull = open(os.devnull, "w")
# os.dup2(_devnull.fileno(), 2)

# RealtimeSTT lives outside the project tree (sibling of the project root).
# File is now <root>/ai/stt.py, so parents[2] is the project's parent.
# If RealtimeSTT is pip-installed instead, this line can be removed.
sys.path.append(str(Path(__file__).resolve().parents[2]))

from RealtimeSTT import AudioToTextRecorder           # noqa: E402

from config import RESET, EXECUTER, EAR, ts               # noqa: E402
from ai.tts import speak, speak_sentences         # noqa: E402
from ai.llm import prompt_router_model_stream         # noqa: E402

# ── Wake-word config ──────────────────────────────────────────────────────────
HOT_WORDS   = frozenset({"miller"})
STRIP_WORDS = frozenset({"hey", "miller"})

_PUNCT_RE = re.compile(r"[^\w\s]")
_STRIP_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(w) for w in STRIP_WORDS) + r")\b"
)

# State labels emitted via on_state callback
STATE_LISTENING  = "listening"
STATE_PROCESSING = "processing"
STATE_SPEAKING   = "speaking"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _hot_word_in(text: str) -> bool:
    words = _PUNCT_RE.sub("", text.lower()).split()
    return bool(HOT_WORDS.intersection(words[:2]))


def _clean_prompt(text: str) -> str:
    text = _PUNCT_RE.sub("", text.lower()).strip()
    return _STRIP_RE.sub("", text).strip()


def _make_recorder() -> AudioToTextRecorder:
    return AudioToTextRecorder(
        spinner=False,
        model="small.en",
        device="cuda",
        language="en",
        silero_sensitivity=0.9,
        webrtc_sensitivity=1,
        post_speech_silence_duration=0.3,
        min_length_of_recording=0.2,
        min_gap_between_recordings=0,
    )


# ── Main loop ─────────────────────────────────────────────────────────────────

def run_stt(
    on_transcription: Optional[Callable[[str], None]] = None,
    on_sentence:      Optional[Callable[[str], None]] = None,
    on_state:         Optional[Callable[[str], None]] = None,
) -> None:
    """Run the STT loop.

    All three callbacks are optional so run_stt() still works standalone
    (CLI / testing) without any UI attached.

    Args:
        on_transcription: called with the raw transcribed text when the
                          wake word is detected.
        on_sentence:      called with each response sentence as it streams
                          in — before TTS plays it, so the UI can display
                          text in sync with speech.
        on_state:         called with one of STATE_LISTENING,
                          STATE_PROCESSING, or STATE_SPEAKING so the UI
                          can show a visual indicator.
    """
    def _emit_state(s: str) -> None:
        if on_state:
            on_state(s)

    recorder      = _make_recorder()
    skip_hot_word = False

    print(f"{ts()}{EAR}[Ear]: Listening{RESET}")
    speak("All models loaded", 4)
    _emit_state(STATE_LISTENING)

    while True:
        text = recorder.text()
        if not text:
            continue

        print(f"{ts()}{EAR}[Ear]: {text}{RESET}")

        woke_via_followup = skip_hot_word
        skip_hot_word = False               # consume immediately (one-shot)

        if not (woke_via_followup or _hot_word_in(text)):
            continue

        if on_transcription:
            on_transcription(text)

        _emit_state(STATE_PROCESSING)

        sentence_stream = prompt_router_model_stream(_clean_prompt(text))
        try:
            full_response = speak_sentences(sentence_stream, 4, on_sentence=on_sentence)
        except Exception as e:
            print(f"{ts()}{EAR}[Ear] TTS error: {e}{RESET}")
            full_response = ""

        if full_response:
            print(f"{ts()}{EXECUTER}[Executer]: {full_response}{RESET}")

        _emit_state(STATE_LISTENING)
        # Arm at most ONE wake-word-free follow-up, and only after a primary
        # (wake-word) turn whose answer actually ended with a question. A
        # follow-up turn never re-arms, so the mic can't stay open on ambient
        # or TV speech the way "'?' in full_response" allowed.
        skip_hot_word = (not woke_via_followup) and full_response.rstrip().endswith("?")
        recorder.start()


if __name__ == "__main__":
    run_stt()