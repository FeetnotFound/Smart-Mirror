#!/usr/bin/env bash
# setup_mirror_os.sh — turn a fresh Ubuntu 22.04+ Server install into Mirror OS
#
# What this does:
#   1. Installs Xorg and all runtime dependencies
#   2. Creates a dedicated 'mirror' user
#   3. Copies this project to /home/mirror/mirror/
#   4. Configures autologin → startx → mirror app on every boot
#   5. Disables screensaver / DPMS (screen never blanks)
#   6. Sets hostname to 'mirror' and enables mDNS (mirror.local)
#   7. Grants the Python binary cap_net_bind_service (port 80)
#   8. Runs install.sh to create the venv and install Python deps
#
# Run from the project root as a regular user with sudo rights:
#   bash setup_mirror_os.sh
#
# To also install voice control afterwards:
#   bash install_ai.sh
#
# To build a bootable ISO from this setup (advanced):
#   See comments at the bottom of this file.

set -euo pipefail

MIRROR_USER="mirror"
MIRROR_HOME="/home/${MIRROR_USER}"
INSTALL_DIR="${MIRROR_HOME}/mirror"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${GREEN}[setup]${NC} $*"; }
warn()  { echo -e "${YELLOW}[setup]${NC} $*"; }
error() { echo -e "${RED}[setup]${NC} $*" >&2; exit 1; }
step()  { echo -e "\n${CYAN}══ $* ══${NC}"; }

# ── Preflight ─────────────────────────────────────────────────────────────────
[[ $EUID -ne 0 ]] && error "Run this script with sudo: sudo bash setup_mirror_os.sh"

step "Preflight"
info "Target user:    ${MIRROR_USER}"
info "Install path:   ${INSTALL_DIR}"
info "Source path:    ${SCRIPT_DIR}"

# ── 1. System packages ────────────────────────────────────────────────────────
step "System packages"
apt-get update -qq
apt-get install -y \
  python3 python3-venv python3-pip \
  xorg xinit x11-xserver-utils \
  libxcb-xinerama0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
  libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-xfixes0 \
  libxcb-cursor0 libxcb-xkb1 libxkbcommon-x11-0 \
  libgl1-mesa-glx libglib2.0-0 libglib2.0-dev \
  fonts-dejavu-core fontconfig \
  avahi-daemon avahi-utils libnss-mdns \
  openssh-server \
  alsa-utils portaudio19-dev libdbus-1-dev \
  libcap2-bin \
  ca-certificates curl git \
  unclutter   # hides the mouse cursor after a short idle

# ── 2. Create mirror user ─────────────────────────────────────────────────────
step "Mirror user"
if id "${MIRROR_USER}" &>/dev/null; then
  info "User '${MIRROR_USER}' already exists"
else
  useradd -m -s /bin/bash -G audio,video,input "${MIRROR_USER}"
  info "Created user '${MIRROR_USER}'"
fi
echo "${MIRROR_USER} ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/mirror
chmod 440 /etc/sudoers.d/mirror
info "Passwordless sudo enabled for ${MIRROR_USER}"

# ── 3. Copy project ───────────────────────────────────────────────────────────
step "Copy project to ${INSTALL_DIR}"
rsync -a --exclude='.mirror/' --exclude='__pycache__/' --exclude='*.pyc' \
  "${SCRIPT_DIR}/" "${INSTALL_DIR}/"
mkdir -p "${INSTALL_DIR}/ui_backend/data"
chown -R "${MIRROR_USER}:${MIRROR_USER}" "${INSTALL_DIR}"
info "Project synced"

# ── 4. Python venv + dependencies ─────────────────────────────────────────────
step "Python environment"
sudo -u "${MIRROR_USER}" bash "${INSTALL_DIR}/install.sh"
# Re-own everything after install in case any step created root-owned files
chown -R "${MIRROR_USER}:${MIRROR_USER}" "${INSTALL_DIR}"

# ── 5. Grant port-80 capability ───────────────────────────────────────────────
step "Port 80 capability"
PYTHON_BIN="$(realpath "${INSTALL_DIR}/.mirror/bin/python")"
setcap 'cap_net_bind_service=+ep' "${PYTHON_BIN}"
info "setcap applied to ${PYTHON_BIN}"

# ── 6. Autologin on tty1 ─────────────────────────────────────────────────────
step "Autologin"
mkdir -p /etc/systemd/system/getty@tty1.service.d
cat > /etc/systemd/system/getty@tty1.service.d/autologin.conf <<EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin ${MIRROR_USER} --noclear %I \$TERM
EOF
info "Autologin configured for ${MIRROR_USER} on tty1"

# ── 7. .bash_profile: auto-startx on tty1 ────────────────────────────────────
step "Auto-startx"
cat > "${MIRROR_HOME}/.bash_profile" <<'EOF'
# Auto-start X on tty1 only (so SSH sessions don't try to launch X)
if [[ -z "${DISPLAY}" && "$(tty)" == "/dev/tty1" ]]; then
    exec startx
fi
EOF
chown "${MIRROR_USER}:${MIRROR_USER}" "${MIRROR_HOME}/.bash_profile"

# ── 8. .xinitrc: launch the mirror ───────────────────────────────────────────
step ".xinitrc"
cat > "${MIRROR_HOME}/.xinitrc" <<XEOF
#!/bin/bash
xset s off
xset -dpms
xset s noblank
unclutter -idle 3 -root &

# Force software rendering — required on Pi (vc4/v3d lacks full OpenGL 3.x)
# and harmless on x86 (llvmpipe fallback still renders correctly)
export QT_QPA_PLATFORM=xcb
export QT_OPENGL=software
export LIBGL_ALWAYS_SOFTWARE=1

while true; do
    cd "${INSTALL_DIR}"
    "${INSTALL_DIR}/.mirror/bin/python" main.py
    sleep 2
done
XEOF
chmod +x "${MIRROR_HOME}/.xinitrc"
chown "${MIRROR_USER}:${MIRROR_USER}" "${MIRROR_HOME}/.xinitrc"
info ".xinitrc written"

# ── 9. Hostname + mDNS ───────────────────────────────────────────────────────
step "Hostname / mDNS"
OLD_HOSTNAME="$(hostname)"
if [[ "${OLD_HOSTNAME}" != "mirror" ]]; then
  read -rp "  Set hostname to 'mirror'? (current: ${OLD_HOSTNAME}) [y/N] " REPLY
  if [[ "${REPLY,,}" == "y" ]]; then
    hostnamectl set-hostname mirror
    # Update /etc/hosts so 127.0.1.1 still resolves
    sed -i "s/127\.0\.1\.1.*/127.0.1.1\tmirror/" /etc/hosts
    info "Hostname → mirror  (accessible at mirror.local)"
  fi
fi
systemctl enable --now avahi-daemon
info "mDNS (avahi) enabled — device reachable at $(hostname).local"

# ── 10. SSH ───────────────────────────────────────────────────────────────────
step "SSH"
systemctl enable --now ssh
info "SSH enabled — remote access available"

# ── 11a. Auto-update service ──────────────────────────────────────────────────
step "Auto-update service"
cat > /etc/systemd/system/mirror-autoupdate.service <<EOF
[Unit]
Description=Mirror OS Auto-Update
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=${MIRROR_USER}
WorkingDirectory=${INSTALL_DIR}
ExecStart=/bin/bash -c '\
    git pull origin main 2>&1 | tee -a /var/log/mirror-update.log && \
    ${INSTALL_DIR}/.mirror/bin/pip install -q -r ${INSTALL_DIR}/requirements-base.txt \
        >> /var/log/mirror-update.log 2>&1'
StandardOutput=journal
StandardError=journal
EOF

cat > /etc/systemd/system/mirror-autoupdate.timer <<'EOF'
[Unit]
Description=Mirror OS Auto-Update Timer

[Timer]
OnCalendar=*-*-* 03:00:00
RandomizedDelaySec=600
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now mirror-autoupdate.timer
info "Auto-update enabled — checks for updates nightly at 3 AM"

# ── 11b. Shairport-sync (AirPlay) ────────────────────────────────────────────
step "Shairport-sync (AirPlay)"
apt-get install -y shairport-sync

# Run as mirror user so it can reach the PipeWire audio session
mkdir -p /etc/systemd/system/shairport-sync.service.d
cat > /etc/systemd/system/shairport-sync.service.d/mirror.conf <<EOF
[Service]
User=${MIRROR_USER}
Environment=XDG_RUNTIME_DIR=/run/user/1000
EOF

# D-Bus policy: allow mirror user to own the MPRIS bus name
cat > /etc/dbus-1/system.d/shairport-sync.conf <<EOF
<!DOCTYPE busconfig PUBLIC
 "-//freedesktop//DTD D-BUS Bus Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig>
  <policy user="${MIRROR_USER}">
    <allow own="org.mpris.MediaPlayer2.ShairportSync"/>
    <allow own="org.gnome.ShairportSync"/>
  </policy>
  <policy context="default">
    <allow send_destination="org.mpris.MediaPlayer2.ShairportSync"/>
    <allow receive_sender="org.mpris.MediaPlayer2.ShairportSync"/>
    <allow send_destination="org.gnome.ShairportSync"/>
    <allow receive_sender="org.gnome.ShairportSync"/>
  </policy>
</busconfig>
EOF
systemctl reload dbus || true
systemctl daemon-reload
systemctl enable --now shairport-sync
info "Shairport-sync enabled — AirPlay receiver active"

# ── 11. Firewall ──────────────────────────────────────────────────────────────
step "Firewall"
if command -v ufw &>/dev/null; then
  ufw allow ssh   comment 'mirror-ssh'  2>/dev/null || true
  ufw allow 80    comment 'mirror-web'  2>/dev/null || true
  info "ufw: SSH and port 80 allowed"
fi

# ── 12a. Raspberry Pi GPU driver ─────────────────────────────────────────────
# On Pi 4/5, the vc4-kms-v3d overlay is required for /dev/dri/card0 to exist.
# Without it Xorg falls back to fbdev and Qt cannot render any windows.
CONFIG_TXT="/boot/firmware/config.txt"
if [[ -f "${CONFIG_TXT}" ]]; then
    step "Raspberry Pi GPU driver"
    if ! grep -q "vc4-kms-v3d" "${CONFIG_TXT}"; then
        # Insert into [pi4] block if present, otherwise append under [all]
        if grep -q "^\[pi4\]" "${CONFIG_TXT}"; then
            sed -i '/^\[pi4\]/a dtoverlay=vc4-fkms-v3d\ngpu_mem=128' "${CONFIG_TXT}"
        else
            printf '\n[all]\ndtoverlay=vc4-fkms-v3d\ngpu_mem=128\n' >> "${CONFIG_TXT}"
        fi
        info "vc4-kms-v3d overlay added to ${CONFIG_TXT}"
    else
        info "vc4-kms-v3d already configured"
    fi
fi

# ── 12. Disable automatic sleep / screen power ───────────────────────────────
step "Power management"
# Kernel doesn't blank the console
echo -e '\n# Mirror OS — disable console blank\nGRUB_CMDLINE_LINUX_DEFAULT="quiet splash consoleblank=0"' \
  >> /etc/default/grub 2>/dev/null || true
update-grub 2>/dev/null || true

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
info "Mirror OS setup complete."
info ""
info "Reboot to start the mirror:"
info "  sudo reboot"
info ""
info "After reboot the device will:"
info "  • Auto-login as '${MIRROR_USER}'"
info "  • Launch X and start the mirror app"
info "  • Serve the web config at http://$(hostname).local"
info ""
info "SSH into this machine anytime:"
info "  ssh ${MIRROR_USER}@$(hostname).local"
info ""
info "To add voice control: bash ${INSTALL_DIR}/install_ai.sh"

# ── ISO building (advanced) ───────────────────────────────────────────────────
# To create a bootable USB image from an existing configured system:
#
#   1. Install live-build on a Debian/Ubuntu machine:
#        sudo apt install live-build
#
#   2. Create a build directory and configure:
#        mkdir mirror-live && cd mirror-live
#        lb config \
#          --distribution jammy \
#          --archive-areas "main restricted universe" \
#          --debian-installer none \
#          --bootappend-live "boot=live username=mirror autologin" \
#          --memtest none
#
#   3. Add this project and packages to the live build hooks:
#        mkdir -p config/hooks/live
#        # (copy your hook scripts that run setup_mirror_os.sh inside the chroot)
#
#   4. Build:
#        sudo lb build
#
#   This produces a .iso file you can flash to a USB drive with:
#        sudo dd if=live-image-amd64.hybrid.iso of=/dev/sdX bs=4M status=progress
#
# For Raspberry Pi images, use pi-gen:
#   https://github.com/RPi-Distro/pi-gen
#   Add a stage that runs this setup_mirror_os.sh and you get a flashable .img
