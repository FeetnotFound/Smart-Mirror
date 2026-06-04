import queue
import threading
import subprocess
from typing import Callable, Iterable, Optional

from config import VOICE, RESET, ts
from model_names import (
    ENGLISH_FEMALE_1, ENGLISH_FEMALE_2,
    GERMAN_MALE_1, JARVIS_HIGH, JARVIS_MEDIUM,
)

_MODEL_MAP: dict[int, str] = {
    1: ENGLISH_FEMALE_1,
    2: ENGLISH_FEMALE_2,
    3: GERMAN_MALE_1,
    4: JARVIS_HIGH,
    5: JARVIS_MEDIUM,
}

_CHUNK   = 4096   # bytes read from piper at a time
_Q_AUDIO = "a"    # audio chunk message
_Q_TEXT  = "t"    # sentence-text message  (fires on_sentence on consumer side)
_Q_DONE  = "d"    # sentinel


def speak(text: str, model: int) -> None:
    """Single-shot TTS for short system messages."""
    model_path = _MODEL_MAP.get(model)
    if model_path is None:
        print(f"{ts()}{VOICE}[Voice] Unknown model ID: {model}{RESET}")
        return
    try:
        piper = subprocess.Popen(
            ["piper", "--model", model_path, "--output-raw"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        raw_audio, _ = piper.communicate(input=text.encode())
        print(f"{ts()}{VOICE}[Voice] Playing voice {model}{RESET}")
        aplay = subprocess.Popen(
            ["aplay", "-r", "22050", "-f", "S16_LE", "-c", "1", "-t", "raw"],
            stdin=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        aplay.communicate(input=raw_audio)
    except FileNotFoundError as e:
        print(f"{ts()}{VOICE}[Voice] TTS binary not found: {e}{RESET}")
    except Exception as e:
        print(f"{ts()}{VOICE}[Voice] TTS error: {e}{RESET}")


def speak_sentences(
    sentences:   Iterable[str],
    model:       int,
    on_sentence: Optional[Callable[[str], None]] = None,
) -> str:
    """Stream sentences to a single persistent aplay process.

    Pipeline per sentence
    ─────────────────────
    piper stdout  ──4 KB chunks──►  queue  ──►  aplay stdin
                                      ▲
                              producer thread

    Why this is faster than the old approach
    ─────────────────────────────────────────
    Old: piper.communicate() blocks until ALL audio is synthesised, then a
         brand-new aplay starts.  Gap = full synthesis time + aplay startup.

    New: aplay starts once for the whole response.  The producer reads piper
         stdout in 4 KB chunks and enqueues them immediately.  aplay starts
         playing after the first chunk arrives (~100 ms) rather than after the
         full sentence is synthesised (~500 ms+).  Because aplay stays alive
         between sentences there is also no silence gap between them.

    on_sentence fires on the consumer side the moment the first audio chunk
    for a sentence is dequeued — text and voice appear in sync instead of
    text appearing ~500 ms before voice.
    """
    model_path = _MODEL_MAP.get(model)
    if model_path is None:
        print(f"{ts()}{VOICE}[Voice] Unknown model ID: {model}{RESET}")
        return ""

    # Large enough queue so piper can stay a sentence ahead without blocking.
    msg_q: queue.Queue[tuple] = queue.Queue(maxsize=32)
    spoken: list[str] = []

    # ── Producer: one piper per sentence, streamed in chunks ─────────────────
    def _producer() -> None:
        try:
            for text in sentences:
                text = text.strip()
                if not text:
                    continue
                spoken.append(text)

                piper = subprocess.Popen(
                    ["piper", "--model", model_path, "--output-raw"],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
                piper.stdin.write(text.encode())
                piper.stdin.close()

                first = True
                while True:
                    chunk = piper.stdout.read(_CHUNK)
                    if not chunk:
                        break
                    if first:
                        # Emit text label with the first audio chunk so
                        # on_sentence fires exactly when voice starts.
                        msg_q.put((_Q_TEXT, text))
                        first = False
                    msg_q.put((_Q_AUDIO, chunk))

                try:
                    piper.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    piper.kill()
                    piper.wait()

        except Exception as e:
            print(f"{ts()}{VOICE}[Voice] TTS error: {e}{RESET}")
        finally:
            msg_q.put((_Q_DONE, None))

    producer = threading.Thread(target=_producer, daemon=True)
    producer.start()

    # ── Consumer: one aplay for the whole response ────────────────────────────
    # NOTE: this fires when aplay opens, BEFORE any audio exists. The real
    # audio-start timestamp is the "first audio" line below.
    print(f"{ts()}{VOICE}[Voice] Opening output (voice {model}){RESET}")

    aplay = subprocess.Popen(
        ["aplay", "-r", "22050", "-f", "S16_LE", "-c", "1", "-t", "raw"],
        stdin=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )

    first_audio = True

    try:
        while True:
            try:
                kind, value = msg_q.get(timeout=30)
            except queue.Empty:
                # Producer died without sending _Q_DONE
                break
            if kind == _Q_DONE:
                break
            elif kind == _Q_TEXT:
                if on_sentence:
                    on_sentence(value)      # text + voice appear together
            else:                           # _Q_AUDIO
                if first_audio:
                    print(f"{ts()}{VOICE}[Voice] first audio (voice {model}){RESET}")
                    first_audio = False
                aplay.stdin.write(value)
    except BrokenPipeError:
        pass
    except Exception as e:
        print(f"{ts()}{VOICE}[Voice] Playback error: {e}{RESET}")
    finally:
        try:
            aplay.stdin.close()
        except OSError:
            pass
        aplay.wait()

    producer.join(timeout=15)
    return " ".join(spoken)