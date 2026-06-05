#!/usr/bin/env bash
# install.sh — set up Mirror for standard operation (no AI, no AirPlay audio)
#
# Run from the project root:
#   bash install.sh
#
# What this does:
#   1. Installs system packages (Qt libs, Python, fonts, avahi)
#   2. Creates a Python virtual environment at .mirror/
#   3. Installs Python packages from requirements-base.txt
#   4. Grants the Python binary cap_net_bind_service so the web config
#      can listen on port 80 without running as root
#   5. Installs a systemd service so the web config starts at boot,
#      even before you run the mirror display
#   6. Creates variables.env template if not already present
#
# To add voice control:   bash install_ai.sh
# To add AirPlay audio:   bash install_shairport.sh

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="${PROJECT_DIR}/.mirror"
BASE_REQS="${PROJECT_DIR}/requirements-base.txt"
SERVICE_NAME="mirror-web"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33d'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${GREEN}[install]${NC} $*"; }
warn()  { echo -e "${YELLOW}[install]${NC} $*"; }
error() { echo -e "${RED}[install]${NC} $*" >&2; exit 1; }
step()  { echo -e "\n${CYAN}══ $* ══${NC}"; }

# ── 1. System packages ────────────────────────────────────────────────────────
step "System packages"
sudo apt-get update -qq
sudo apt-get install -y \
  python3 python3-venv python3-pip \
  libxcb-xinerama0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
  libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-xfixes0 \
  libxcb-util1 libxcb-cursor0 \
  libgl1-mesa-glx libglib2.0-0 \
  fonts-dejavu-core fontconfig \
  avahi-daemon avahi-utils libnss-mdns \
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

# ── 5. Web config systemd service ────────────────────────────────────────────
step "Web config service (mirror-web)"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=Smart Mirror Web Config
After=network.target avahi-daemon.service
Wants=network.target

[Service]
Type=simple
WorkingDirectory=${PROJECT_DIR}
ExecStart=${VENV_DIR}/bin/python -m web_config.server
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}"
sudo systemctl restart "${SERVICE_NAME}"
info "Web config service installed and started"
info "Access at: http://$(hostname).local"

# ── 6. variables.env ──────────────────────────────────────────────────────────
ENV_FILE="${PROJECT_DIR}/variables.env"
if [ ! -f "$ENV_FILE" ]; then
  step "Environment file"
  cp "${PROJECT_DIR}/variables.env" "$ENV_FILE" 2>/dev/null || \
  cat > "$ENV_FILE" <<'ENVEOF'
ICLOUD_USERNAME=your@icloud.com
ICLOUD_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
HUE_BRIDGE_IP=
HUE_USERNAME=
HA_BASE_URL=
HA_TOKEN=
ENVEOF
  warn "Edit variables.env with your iCloud credentials before running the mirror."
else
  info "variables.env already exists — skipping."
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
info "Installation complete."
info ""
info "Web config is already running at:"
info "  http://$(hostname).local  (from any device on your network)"
info ""
info "To start the mirror display:"
info "  source .mirror/bin/activate && python main.py"
info ""
info "Optional add-ons:"
info "  Voice control  →  bash install_ai.sh"
info "  AirPlay audio  →  bash install_shairport.sh"
