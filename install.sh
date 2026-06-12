#!/usr/bin/env bash
# install.sh — set up Mirror for standard operation (no AI, no AirPlay audio)
#
# Run from the project root as a regular user with sudo rights:
#   bash install.sh
#
# What this does:
#   1. Installs system packages (Qt libs, Python, fonts, avahi, audio)
#   2. Creates a Python virtual environment at .mirror/
#   3. Installs Python packages from requirements-base.txt
#   4. Grants the Python binary cap_net_bind_service (port 80)
#   5. Creates variables.env template if not already present
#   6. Ensures all project files are owned by the calling user
#
# To add voice control:   bash install_voice.sh
# To add AI responses:    bash install_ai.sh
# To add AirPlay audio:   bash install_shairport.sh

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="${PROJECT_DIR}/.mirror"
BASE_REQS="${PROJECT_DIR}/requirements-base.txt"
CURRENT_USER="$(whoami)"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${GREEN}[install]${NC} $*"; }
warn()  { echo -e "${YELLOW}[install]${NC} $*"; }
error() { echo -e "${RED}[install]${NC} $*" >&2; exit 1; }
step()  { echo -e "\n${CYAN}══ $* ══${NC}"; }

# ── 0. Fix ownership up front ─────────────────────────────────────────────────
# git clone as root leaves files owned by root; chown before anything else so
# venv creation and pip installs can write to the project directory.
step "Fixing ownership"
sudo chown -R "${CURRENT_USER}:${CURRENT_USER}" "${PROJECT_DIR}"
info "Ownership set to ${CURRENT_USER}"

# ── 1. System packages ────────────────────────────────────────────────────────
step "System packages"
sudo apt-get update -qq
sudo apt-get install -y \
  python3 python3-venv python3-pip \
  libxcb-xinerama0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
  libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-xfixes0 \
  libxcb-util1 libxcb-cursor0 libxcb-xkb1 libxkbcommon-x11-0 \
  libgl1-mesa-glx libglib2.0-0 libglib2.0-dev \
  fonts-dejavu-core fontconfig \
  avahi-daemon avahi-utils libnss-mdns \
  alsa-utils portaudio19-dev libdbus-1-dev \
  libcap2-bin \
  ca-certificates curl git

# Enable mDNS so mirror.local resolves on the network
if ! grep -q "mdns4_minimal" /etc/nsswitch.conf 2>/dev/null; then
  sudo sed -i 's/^hosts:.*/hosts: files mdns4_minimal [NOTFOUND=return] dns/' /etc/nsswitch.conf
fi
sudo systemctl enable --now avahi-daemon 2>/dev/null || true
info "mDNS enabled — mirror reachable at $(hostname).local"

# ── 2. Virtual environment ────────────────────────────────────────────────────
step "Python virtual environment"
if [ -d "$VENV_DIR" ]; then
  info "Virtual environment already exists at $VENV_DIR"
else
  python3 -m venv "$VENV_DIR"
  info "Created virtual environment at $VENV_DIR"
fi
source "$VENV_DIR/bin/activate"
pip install --upgrade pip --quiet

# ── 3. Python packages ────────────────────────────────────────────────────────
step "Python packages"
pip install -r "$BASE_REQS"

# ── 4. Port 80 capability ─────────────────────────────────────────────────────
step "Port 80 (web config)"
REAL_PY="$(readlink -f "${VENV_DIR}/bin/python")"
if sudo setcap 'cap_net_bind_service=+ep' "$REAL_PY" 2>/dev/null; then
  info "Port 80 granted to $REAL_PY"
else
  warn "setcap failed — web config will use port 8080 instead of 80"
fi

# ── 5. variables.env ──────────────────────────────────────────────────────────
ENV_FILE="${PROJECT_DIR}/variables.env"
if [ ! -f "$ENV_FILE" ]; then
  step "Environment file"
  cat > "$ENV_FILE" <<'ENVEOF'
ICLOUD_USERNAME=your@icloud.com
ICLOUD_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
HUE_BRIDGE_IP=
HUE_USERNAME=
HA_BASE_URL=
HA_TOKEN=
ENVEOF
  warn "Edit variables.env with your credentials before running the mirror."
else
  info "variables.env already exists — skipping."
fi

# ── 6. Fix ownership ──────────────────────────────────────────────────────────
step "Fixing file ownership"
sudo chown -R "${CURRENT_USER}:${CURRENT_USER}" "${PROJECT_DIR}"
info "Ownership set to ${CURRENT_USER}"

# ── 7. Update .xinitrc to point at this directory ─────────────────────────────
# Handles re-cloning to a different folder name (e.g. mirror → Smart-Mirror).
XINITRC="${HOME}/.xinitrc"
if [ -f "$XINITRC" ]; then
  step "Updating .xinitrc"
  # Extract the old project path from the Python binary line in .xinitrc
  OLD_PATH=$(grep -o '"[^"]*\.mirror/bin/python"' "$XINITRC" \
             | sed 's|"||g;s|/.mirror/bin/python||' | head -1)
  if [ -n "$OLD_PATH" ] && [ "$OLD_PATH" != "$PROJECT_DIR" ]; then
    sed -i "s|${OLD_PATH}|${PROJECT_DIR}|g" "$XINITRC"
    info ".xinitrc updated: $(basename "$OLD_PATH") → $(basename "$PROJECT_DIR")"
  else
    info ".xinitrc already points to $PROJECT_DIR"
  fi
else
  warn ".xinitrc not found — run setup_mirror_os.sh to create it"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
info "Installation complete."
info ""
info "To start the mirror display:"
info "  source .mirror/bin/activate && python main.py"
info ""
info "The web config starts automatically when the mirror app runs."
info "Access it at: http://$(hostname).local"
info ""
info "Optional add-ons:"
info "  Voice commands  →  bash install_voice.sh"
info "  AI responses    →  bash install_ai.sh"
info "  AirPlay audio   →  bash install_shairport.sh"
