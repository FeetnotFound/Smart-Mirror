import re
import json
import requests
from typing import Iterator

import config
from config import (
    OLLAMA_URL,
    RESET, SYSTEM, EXECUTER,
    QUERY_TIMEOUT, ts,
)

# ── Shared HTTP session (connection pooling) ──────────────────────────────────
session = requests.Session()

# ── TTS cleanup: precompiled once at import ───────────────────────────────────
_CLEAN_PATTERNS = [
    (re.compile(r"#{1,6}\s*"),              ""),      # markdown headers
    (re.compile(r"\*{1,2}([^*]+)\*{1,2}"), r"\1"),   # bold / italic
    (re.compile(r"\n---\n"),                " "),     # horizontal rules
    (re.compile(r"~\d+%"),                  ""),      # tokens like ~85%
    (re.compile(r"\s+"),                    " "),     # collapse whitespace
]

# Sentence boundary: .!? followed by whitespace (good enough for voice)
_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+")

# ── System prompts ────────────────────────────────────────────────────────────
_BRIEF_SYSTEM = (
    "You are a smart mirror voice assistant. "
    "Answer in 1 short sentence. "
    "No lists, no headers, no bold, no markdown, no emojis. Plain spoken English only."
)
_DETAILED_SYSTEM = (
    "You are a smart mirror voice assistant. "
    "Give a concise spoken answer in 3-4 sentences max. "
    "No lists, no headers, no bold, no markdown, no emojis. Plain spoken English only."
)


def clean_for_tts(text: str) -> str:
    for pattern, replacement in _CLEAN_PATTERNS:
        text = pattern.sub(replacement, text)
    return text.strip()


# ── Core streaming query ──────────────────────────────────────────────────────

def _stream_sentences(
    prompt: str,
    max_tokens: int = 150,
    system_msg: str = "",
    think: bool = False,
) -> Iterator[str]:
    """Stream the LLM response and yield one clean, TTS-ready sentence at a time.

    Key latency wins over a blocking query:
      1. TTS starts on the FIRST sentence — not after the full response.
      2. For thinking-mode models, <think>...</think> tokens are transparently
         skipped, so TTS begins as soon as the actual answer starts rather than
         after the (potentially long) reasoning block finishes.
    """
    try:
        print(f"{ts()}{SYSTEM}[System] Streaming model response...{RESET}")
        with session.post(
            f"{OLLAMA_URL}/chat",
            json={
                "model":    config.get_model_name(),
                "messages": [
                    {"role": "system", "content": system_msg},
                    {"role": "user",   "content": prompt},
                ],
                "stream":     True,
                "think":      think,
                "keep_alive": "30m",
                "options":    {"num_predict": max_tokens, "num_ctx": 1024},
            },
            stream=True,
            timeout=QUERY_TIMEOUT,
        ) as resp:
            resp.raise_for_status()

            sentence_buf = ""    # accumulates real response text
            in_think     = False  # are we inside a <think> block?
            think_buf    = ""    # catches </think> if split across tokens

            for raw_line in resp.iter_lines():
                if not raw_line:
                    continue

                chunk = json.loads(raw_line)
                token = chunk.get("message", {}).get("content", "")
                done  = chunk.get("done", False)

                # ── Thinking-block filter ─────────────────────────────────
                # Tokens inside <think>...</think> are the model's internal
                # chain-of-thought; we skip them entirely so TTS starts the
                # moment the visible answer begins.
                if in_think:
                    think_buf += token
                    if "</think>" in think_buf:
                        _, after  = think_buf.split("</think>", 1)
                        think_buf = ""
                        in_think  = False
                        token     = after           # real content after tag
                    else:
                        think_buf = think_buf[-10:]  # keep partial-tag tail
                        if done:
                            break
                        continue

                if "<think>" in token:
                    before, _ = token.split("<think>", 1)
                    sentence_buf += before
                    in_think = True
                    token    = ""

                sentence_buf += token

                # ── Yield complete sentences immediately ──────────────────
                while True:
                    m = _SENTENCE_END_RE.search(sentence_buf)
                    if not m:
                        break
                    sentence     = clean_for_tts(sentence_buf[: m.start() + 1])
                    sentence_buf = sentence_buf[m.end():]
                    if sentence:
                        yield sentence

                if done:
                    break

            # Flush any remaining text (last sentence with no trailing space)
            remainder = clean_for_tts(sentence_buf.strip())
            if remainder:
                yield remainder

    except requests.HTTPError as e:
        print(f"{ts()}{EXECUTER}[Executer] HTTP error: {e}{RESET}")
    except requests.RequestException as e:
        print(f"{ts()}{EXECUTER}[Executer] Request error: {e}{RESET}")
    except Exception as e:
        print(f"{ts()}{EXECUTER}[Executer] Unexpected error: {e}{RESET}")


# ── Public streaming handlers ─────────────────────────────────────────────────

def nonthinking_stream(prompt: str) -> Iterator[str]:
    return _stream_sentences(prompt, max_tokens=120, system_msg=_BRIEF_SYSTEM, think=False)


def thinking_stream(prompt: str) -> Iterator[str]:
    return _stream_sentences(prompt, max_tokens=500, system_msg=_DETAILED_SYSTEM, think=True)


STREAM_FUNCTION_MAP: dict = {
    "nonthinking": nonthinking_stream,
    "thinking":    thinking_stream,
}


def execution_stream(router_result: tuple) -> Iterator[str]:
    """Route to the right streaming handler.

    For commands without a handler yet (control_light, set_timer, …) we fall
    back to a normal spoken answer instead of going silent, so the assistant
    stays responsive while those handlers are still stubs.
    """
    func_name, args = router_result

    stream_handler = STREAM_FUNCTION_MAP.get(func_name)
    if stream_handler:
        yield from stream_handler(**args)
        return

    # Sync fallback for future non-LLM commands (control_light, set_timer, …)
    from ai.executer import FUNCTION_MAP  # local import avoids circular ref
    sync_handler = FUNCTION_MAP.get(func_name)
    if sync_handler:
        result = sync_handler(**args)
        if result:
            yield result
        return

    # No handler implemented yet → answer normally rather than going silent.
    print(f"{ts()}{EXECUTER}[Executer] No handler for {func_name!r}; "
          f"answering normally{RESET}")
    prompt = args.get("raw") or args.get("prompt") or ""
    yield from nonthinking_stream(prompt)


# ── Sync execution (backward compat + non-streaming fallback) ─────────────────

# Non-streaming handlers used by the sync fallback path above
nonthinking = lambda p: "".join(nonthinking_stream(p))
thinking    = lambda p: "".join(thinking_stream(p))

# Backend command handlers — imported here (not at module top) to avoid
# circular imports; executer is imported by llm which is imported by stt.
from ui_backend.timer_backend        import set_timer
from ui_backend.alarm_backend        import set_alarm
from ui_backend.task_backend         import add_task, complete_task
from ui_backend.system_info_backend  import get_system_info
from ui_backend.light_backend        import control_light
from ui_backend.web_search_backend   import web_search
from ui_backend.plug_backend         import control_plug
from ui_backend.ui_control_backend   import control_user_interface

FUNCTION_MAP: dict = {
    "nonthinking":            nonthinking,
    "thinking":               thinking,
    "set_timer":              set_timer,
    "set_alarm":              set_alarm,
    "add_task":               add_task,
    "complete_task":          complete_task,
    "get_system_info":        get_system_info,
    "control_light":          control_light,
    "web_search":             web_search,
    "control_plug":           control_plug,
    "control_user_interface": control_user_interface,
}


def execution(router_result: tuple) -> str:
    """Blocking version: collects the full streamed response into a string."""
    return " ".join(execution_stream(router_result))