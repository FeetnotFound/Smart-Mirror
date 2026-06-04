#!/usr/bin/env bash
# install_ai.sh — install voice-control dependencies for Mirror
#
# Run from the project root:
#   bash install_ai.sh
#
# What this installs:
#   • Ollama          (local LLM server)
#   • qwen3:1.7b      (response model — swap in config.py if you prefer another)
#   • RealtimeSTT     (Whisper-based speech recognition, pulls torch + CUDA libs)
#   • piper-tts       (fast offline text-to-speech)
#   • alsa-utils      (aplay for audio output)
#   • libdbus-1-dev   (D-Bus for the AirPlay music widget)
#
# Requirements:
#   • A virtual environment already exists at .mirror/  (run setup first)
#   • sudo access for system packages
#   • An NVIDIA GPU is strongly recommended (RealtimeSTT uses CUDA by default)
#     — CPU-only works but latency is high; edit ai/stt.py: device="cpu"

set -e

VENV_DIR="$(dirname "$0")/.mirror"
MODEL="qwen3:1.7b"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()    { echo -e "${GREEN}[install_ai]${NC} $*"; }
warn()    { echo -e "${YELLOW}[install_ai]${NC} $*"; }
error()   { echo -e "${RED}[install_ai]${NC} $*" >&2; exit 1; }

# ── 1. Venv check ─────────────────────────────────────────────────────────────
if [ ! -f "$VENV_DIR/bin/activate" ]; then
  error "Virtual environment not found at $VENV_DIR — create it first:
  python3 -m venv .mirror && source .mirror/bin/activate && pip install -r requirements.txt"
fi
source "$VENV_DIR/bin/activate"
info "Using venv: $VENV_DIR"

# ── 2. System packages ────────────────────────────────────────────────────────
info "Installing system packages (requires sudo)..."
sudo apt-get update -qq
sudo apt-get install -y alsa-utils libdbus-1-dev

# ── 3. Python AI packages ─────────────────────────────────────────────────────
info "Installing Python AI packages (RealtimeSTT, piper-tts)..."
info "  This downloads ~2–4 GB of PyTorch and model files on first run."
pip install RealtimeSTT piper-tts

# ── 4. Ollama ─────────────────────────────────────────────────────────────────
if command -v ollama &>/dev/null; then
  info "Ollama already installed ($(ollama --version 2>/dev/null || echo unknown))"
else
  info "Installing Ollama..."
  curl -fsSL https://ollama.ai/install.sh | sh
fi

# Start Ollama in the background if not already running
if ! pgrep -x ollama &>/dev/null; then
  info "Starting Ollama server..."
  ollama serve &>/dev/null &
  sleep 3
fi

# ── 5. Pull model ─────────────────────────────────────────────────────────────
info "Pulling model: $MODEL"
info "  (This may take several minutes on first run)"
ollama pull "$MODEL"

# ── 6. Piper voice models ─────────────────────────────────────────────────────
VOICE_DIR="$(dirname "$0")/models/voice_models"
mkdir -p "$VOICE_DIR"

if ls "$VOICE_DIR"/*.onnx &>/dev/null 2>&1; then
  info "Voice models already present in $VOICE_DIR"
else
  warn "No Piper voice models found in $VOICE_DIR"
  warn "Download a voice from https://github.com/rhasspy/piper/releases"
  warn "and place the .onnx + .onnx.json files in:  $VOICE_DIR/"
  warn "Then update model_names.py to point to it."
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
info "AI dependencies installed successfully."
info ""
info "Next steps:"
info "  1. If no voice model was found above, download one from:"
info "       https://github.com/rhasspy/piper/releases"
info "     and drop the .onnx + .onnx.json into  models/voice_models/"
info ""
info "  2. Edit variables.env with your iCloud and Hue credentials"
info "     (or use the web config page after starting the mirror)"
info ""
info "  3. Start the mirror:"
info "       source .mirror/bin/activate && python main.py"
