#!/usr/bin/env bash
# install.sh — set up Mirror for standard operation (no AI, no AirPlay audio)
#
# Run from the project root:
#   bash install.sh
#
# What this does:
#   • Installs system packages needed by Qt and the calendar backend
#   • Creates a Python virtual environment at .mirror/
#   • Installs Python packages from requirements-base.txt
#
# To add voice control afterwards:  bash install_ai.sh
# To add AirPlay display afterwards: bash install_shairport.sh (if present)

set -e

VENV_DIR="$(dirname "$0")/.mirror"
BASE_REQS="$(dirname "$0")/requirements-base.txt"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${GREEN}[install]${NC} $*"; }
warn()  { echo -e "${YELLOW}[install]${NC} $*"; }
error() { echo -e "${RED}[install]${NC} $*" >&2; exit 1; }
step()  { echo -e "\n${CYAN}══ $* ══${NC}"; }

# ── 1. System packages ────────────────────────────────────────────────────────
step "System packages"
info "Installing Qt and Python system dependencies (requires sudo)..."
sudo apt-get update -qq
sudo apt-get install -y \
  python3 python3-venv python3-pip \
  libxcb-xinerama0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
  libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-xfixes0 \
  libgl1-mesa-glx libglib2.0-0 \
  fonts-dejavu-core fontconfig \
  ca-certificates curl

# ── 2. Virtual environment ────────────────────────────────────────────────────
step "Python virtual environment"
if [ -d "$VENV_DIR" ]; then
  info "Virtual environment already exists at $VENV_DIR"
else
  info "Creating virtual environment at $VENV_DIR..."
  python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"
info "Upgrading pip..."
pip install --upgrade pip --quiet

# ── 3. Python packages ────────────────────────────────────────────────────────
step "Python packages"
info "Installing from requirements-base.txt..."
pip install -r "$BASE_REQS"

# ── 4. variables.env ──────────────────────────────────────────────────────────
ENV_FILE="$(dirname "$0")/variables.env"
if [ ! -f "$ENV_FILE" ]; then
  step "Environment file"
  info "Creating variables.env template..."
  cat > "$ENV_FILE" <<'ENVEOF'
# Mirror environment — fill in your credentials
ICLOUD_USERNAME=your@icloud.com
ICLOUD_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx

# Philips Hue (optional)
HUE_BRIDGE_IP=
HUE_USERNAME=

# Home Assistant (optional)
HA_BASE_URL=
HA_TOKEN=
ENVEOF
  warn "Edit variables.env with your iCloud credentials before running the mirror."
else
  info "variables.env already exists — skipping template."
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
info "Base installation complete."
info ""
info "To start the mirror:"
info "  source .mirror/bin/activate && python main.py"
info ""
info "Optional add-ons:"
info "  Voice control  →  bash install_ai.sh"
info ""
info "Edit variables.env (or use the web config page at http://$(hostname).local)"
info "with your iCloud credentials before running."
