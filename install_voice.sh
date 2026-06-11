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
info "Installing RealtimeSTT and Piper TTS..."
info "  Downloads PyTorch + Whisper model (~1-2 GB) on first run."
pip install RealtimeSTT piper-tts

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
