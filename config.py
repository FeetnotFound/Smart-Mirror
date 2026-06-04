import time as _time

def ts() -> str:
    """Return a dark-grey HH:MM:SS.mmm prefix for timestamped debug prints.

    Example output:
        14:32:10.003 [Ear]: Hey Miller, what is the time?
        14:32:10.005 [System] Streaming model response...
        14:32:11.249 [Router]: ('nonthinking', {'prompt': ...})
        14:32:11.814 [Voice] Streaming voice 4

    Subtract any two lines to see exactly where time is being spent.
    """
    t  = _time.time()
    ms = int((t % 1) * 1000)
    s  = _time.localtime(t)
    return f"\033[90m{s.tm_hour:02d}:{s.tm_min:02d}:{s.tm_sec:02d}.{ms:03d}\033[0m "


# ─────────────────────────────────────────────
#  Model configuration
# ─────────────────────────────────────────────
OLLAMA_URL        = "http://localhost:11434/api"
MODEL_NAME        = "qwen3:1.7b"
LOCAL_ROUTER_PATH = "./models/router_models/qwen-local-instruct"
BASE_MODEL_PATH   = "./models/router_models/Qwen-Local-Folder"

# ─────────────────────────────────────────────
#  HTTP timeouts (seconds)
# ─────────────────────────────────────────────
LOAD_TIMEOUT  = 120   # warm-up / first-load call
QUERY_TIMEOUT = 60    # regular inference call

# ─────────────────────────────────────────────
#  Terminal colors
# ─────────────────────────────────────────────
RESET    = "\033[0m"
BOLD     = "\033[1m"
SYSTEM   = "\033[90m"   # dark grey
AI       = "\033[36m"   # cyan
VOICE    = "\033[32m"   # green
ROUTER   = "\033[33m"   # yellow
EXECUTER = "\033[35m"   # magenta
EAR      = "\033[34m"   # blue