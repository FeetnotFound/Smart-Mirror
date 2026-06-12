#!/usr/bin/env bash
# install_voice.sh — voice commands without full AI
#
# Installs:
#   • RealtimeSTT  (Whisper speech recognition — wake word + commands)
#   • piper-tts    (offline text-to-speech for spoken feedback)
#
# Does NOT install Ollama or any LLM model.
# Voice commands (timers, lights, alarms, tasks) work without AI.
# For AI responses to open-ended questions, run install_ai.sh after this.
#
# Run from the project root:
#   bash install_voice.sh

set -e

VENV_DIR="$(dirname "$0")/.mirror"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[install_voice]${NC} $*"; }
warn()  { echo -e "${YELLOW}[install_voice]${NC} $*"; }
error() { echo -e "${RED}[install_voice]${NC} $*" >&2; exit 1; }

# ── Venv check ────────────────────────────────────────────────────────────────
if [ ! -f "$VENV_DIR/bin/activate" ]; then
  error "Virtual environment not found at $VENV_DIR — run install.sh first"
fi
source "$VENV_DIR/bin/activate"
info "Using venv: $VENV_DIR"

# ── Python packages ───────────────────────────────────────────────────────────
# Install CPU-only PyTorch first so RealtimeSTT doesn't pull in CUDA (multi-GB,
# useless on Pi/non-NVIDIA hardware).
info "Installing CPU-only PyTorch and torchaudio..."
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu

info "Installing RealtimeSTT and Piper TTS..."
pip install RealtimeSTT piper-tts

# Pre-trust silero-vad so RealtimeSTT never hits the interactive y/n prompt.
# Write the entry directly to PyTorch Hub's trusted_list file.
info "Pre-trusting silero-vad for PyTorch Hub..."
python3 - <<'PYEOF'
import torch, os, sys
try:
    hub_dir = torch.hub.get_dir()
    os.makedirs(hub_dir, exist_ok=True)
    trusted_file = os.path.join(hub_dir, "trusted_list")
    existing = open(trusted_file).read() if os.path.exists(trusted_file) else ""
    entries = ["snakers4/silero-vad", "snakers4_silero-vad_master", "snakers4_silero-vad_main"]
    with open(trusted_file, "a") as f:
        for entry in entries:
            if entry not in existing:
                f.write(entry + "\n")
    torch.hub.load("snakers4/silero-vad", "silero_vad", trust_repo=True, verbose=False)
    print("[install_voice] silero-vad trusted and cached OK")
except Exception as e:
    print(f"[install_voice] warning: silero-vad pre-cache failed: {e}", file=sys.stderr)
PYEOF

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "┌─────────────────────────────────────────────────────────┐"
echo "│  Voice commands installed                               │"
echo "│                                                         │"
echo "│  Say 'Mirror' to activate, then:                        │"
echo "│    Mirror, set a timer for 5 minutes                    │"
echo "│    Mirror, turn on the lights                           │"
echo "│    Mirror, set an alarm for 7am                         │"
echo "│    Mirror, add buy milk to my task list                 │"
echo "│                                                         │"
echo "│  Restart the mirror app to enable voice control.        │"
echo "│                                                         │"
echo "│  For AI responses: bash install_ai.sh                   │"
echo "└─────────────────────────────────────────────────────────┘"
