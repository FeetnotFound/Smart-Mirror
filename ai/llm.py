import threading
from typing import Optional, Iterator

from config import (
    OLLAMA_URL, MODEL_NAME,
    AI, RESET, SYSTEM, ROUTER,
    LOAD_TIMEOUT, ts,
)
from ai.executer import execution_stream, session as http_session
from ai.keyword_router import KeywordRouter as FunctionRouter

# ── Router singleton with thread-safe lazy initialisation ─────────────────────
_router: Optional[FunctionRouter] = None
_router_lock = threading.Lock()


def _get_router() -> FunctionRouter:
    global _router
    if _router is None:                      # fast path (no lock)
        with _router_lock:
            if _router is None:              # double-checked locking
                _load_router()
    return _router  # type: ignore[return-value]


def _load_router() -> None:
    global _router
    try:
        _router = FunctionRouter()
        print(f"{ts()}{ROUTER}[Router] keyword router ready{RESET}")
    except Exception as e:
        print(f"{ts()}{ROUTER}[Router] Failed to load: {e}{RESET}")
        raise


def _load_responder() -> None:
    """Send a cheap warm-up request so the LLM is resident in memory."""
    try:
        print(f"{ts()}{SYSTEM}[System] Warming up response model...{RESET}")
        resp = http_session.post(
            f"{OLLAMA_URL}/generate",
            json={
                "model":      MODEL_NAME,
                "prompt":     "hi",
                "stream":     False,
                "keep_alive": "30m",
                "options":    {"num_predict": 1},
            },
            timeout=LOAD_TIMEOUT,
        )
        if resp.status_code == 200:
            print(f"{ts()}{AI}[AI] {MODEL_NAME} loaded{RESET}")
        else:
            print(f"{ts()}{AI}[AI] {MODEL_NAME} returned status {resp.status_code}{RESET}")
    except Exception as e:
        print(f"{ts()}{AI}[AI] Failed to warm up responder: {e}{RESET}")


# ── Public API ────────────────────────────────────────────────────────────────

def preload_models() -> None:
    """Load the router and warm up the LLM concurrently."""
    print(f"{ts()}{SYSTEM}[System] Preloading models...{RESET}")
    threads = [
        threading.Thread(target=_load_responder, daemon=True),
        threading.Thread(target=_load_router,    daemon=True),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    print(f"{ts()}{SYSTEM}[System] All models loaded{RESET}")


def prompt_router_model_stream(prompt: str) -> Iterator[str]:
    """Route the prompt, then stream sentences from the chosen handler.

    The router is now a sub-millisecond keyword classifier, so there is no
    latency to hide — speculation was removed. First-audio latency is now
    just the router (negligible) plus Ollama's time-to-first-token, and the
    GPU is no longer split between a transformers router and Ollama.
    """
    try:
        func_name, args = _get_router().route(prompt)
    except Exception as e:
        print(f"{ts()}{ROUTER}[Router] Error: {e}{RESET}")
        func_name, args = "nonthinking", {"prompt": prompt}

    print(f"{ts()}{ROUTER}[Router]: {(func_name, args)}{RESET}")
    yield from execution_stream((func_name, args))


# Back-compat aliases
preload_model = preload_models

def prompt_router_model(prompt: str) -> str:
    """Blocking version — joins the full streamed response into one string."""
    return " ".join(prompt_router_model_stream(prompt))