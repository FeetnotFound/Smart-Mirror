#!/usr/bin/env bash
# Install shairport-sync from source with MPRIS + D-Bus + PipeWire support.
# Run as a normal user with sudo access:  bash install_shairport.sh

set -euo pipefail

ok()  { echo -e "\033[32m✓\033[0m  $*"; }
log() { echo -e "\033[34m→\033[0m  $*"; }
err() { echo -e "\033[31m✗\033[0m  $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] && err "Run as a normal user, not root. The script uses sudo where needed."

MIRROR_DIR="$(cd "$(dirname "$0")" && pwd)"
CURRENT_USER="$(whoami)"
CURRENT_UID="$(id -u)"

# ── 1. system packages ────────────────────────────────────────────────────────
log "Installing build dependencies..."
sudo apt-get update -qq
sudo apt-get install -y \
    build-essential git autoconf automake libtool \
    pkg-config \
    libpopt-dev \
    libconfig-dev \
    libssl-dev \
    libavahi-client-dev avahi-daemon \
    libsoxr-dev \
    libasound2-dev \
    libplist-dev \
    libsodium-dev \
    libgcrypt-dev \
    libglib2.0-dev \
    libdbus-1-dev \
    xxd
ok "Build dependencies installed."

# ── 2. dbus-python for the music widget ──────────────────────────────────────
log "Installing dbus-python..."
VENV="$MIRROR_DIR/.mirror"
if [[ -d "$VENV" ]]; then
    "$VENV/bin/pip" install --quiet dbus-python
    ok "dbus-python installed into venv."
else
    pip3 install --user --quiet dbus-python
    ok "dbus-python installed (user)."
fi

# ── 3. clone / update shairport-sync ─────────────────────────────────────────
SRC_DIR="/tmp/shairport-sync-src"
if [[ -d "$SRC_DIR/.git" ]]; then
    log "Updating existing shairport-sync source..."
    git -C "$SRC_DIR" pull --quiet
else
    log "Cloning shairport-sync..."
    git clone --quiet --depth 1 \
        https://github.com/mikebrady/shairport-sync.git "$SRC_DIR"
fi
ok "Source ready."

# ── 4. build ──────────────────────────────────────────────────────────────────
log "Configuring..."
cd "$SRC_DIR"
autoreconf -fi -I /usr/share/aclocal >/dev/null 2>&1

./configure \
    --sysconfdir=/etc \
    --with-alsa \
    --with-avahi \
    --with-ssl=openssl \
    --with-soxr \
    --with-dbus-interface \
    --with-mpris-interface \
    --with-metadata \
    2>&1 | tail -5

log "Building (1–3 min)..."
make -j"$(nproc)" >/dev/null
ok "Build complete."

log "Installing..."
sudo make install >/dev/null
ok "shairport-sync installed to /usr/local/bin."

# ── 5. system user ────────────────────────────────────────────────────────────
# shairport-sync unit file references User=shairport-sync; create it if absent
if ! id shairport-sync &>/dev/null; then
    log "Creating shairport-sync system user..."
    sudo useradd -r -M -s /usr/sbin/nologin shairport-sync
    sudo usermod -a -G audio shairport-sync
    ok "System user created."
fi

# ── 6. config file ────────────────────────────────────────────────────────────
log "Writing /etc/shairport-sync.conf..."
sudo tee /etc/shairport-sync.conf >/dev/null <<EOF
// shairport-sync configuration
general = {
    name = "Mirror";
    volume_range_db = 60;
};

alsa = {
    output_device = "pipewire";   // PipeWire ALSA sink; change to plughw:N,0 for direct ALSA
    // mixer_control_name = "Master";  // omit if sound card has no hardware controls (e.g. AIY Voice HAT)
    audio_backend_buffer_desired_length_in_seconds = 0.5;
};

dbus_interface = "standard";
mpris_interface = "standard";

metadata = {
    enabled = "yes";
    include_cover_art = "yes";
    pipe_name = "/tmp/shairport-sync-metadata";
    pipe_timeout = 5000;
    cover_art_cache_directory = "/tmp/shairport-sync-cover-art";
};
EOF
ok "Config written."

# ── 7. systemd service override (run as logged-in user for PipeWire) ─────────
# The default unit runs as shairport-sync which cannot reach the PipeWire
# socket. Override to run as the current user who owns the PipeWire session.
log "Configuring service to run as $CURRENT_USER (PipeWire access)..."
sudo mkdir -p /etc/systemd/system/shairport-sync.service.d
sudo tee /etc/systemd/system/shairport-sync.service.d/pipewire.conf >/dev/null <<EOF
[Service]
User=$CURRENT_USER
Environment=XDG_RUNTIME_DIR=/run/user/$CURRENT_UID
EOF
ok "Service override written."

# ── 8. D-Bus policy ──────────────────────────────────────────────────────────
# Allow the running user to own the MPRIS bus name so the music widget can
# read now-playing metadata.
log "Installing D-Bus policy..."
sudo tee /etc/dbus-1/system.d/shairport-sync.conf >/dev/null <<EOF
<!DOCTYPE busconfig PUBLIC
 "-//freedesktop//DTD D-Bus Bus Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig>
  <policy user="$CURRENT_USER">
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
sudo systemctl reload dbus
ok "D-Bus policy installed."

# ── 9. enable and start ───────────────────────────────────────────────────────
log "Enabling shairport-sync service..."
sudo systemctl daemon-reload
sudo systemctl enable shairport-sync
sudo systemctl restart shairport-sync
sleep 2

if systemctl is-active --quiet shairport-sync; then
    ok "shairport-sync is running."
    # Quick MPRIS smoke-test
    if [[ -d "$VENV" ]]; then
        "$VENV/bin/python" - <<'PYEOF' 2>/dev/null && ok "MPRIS D-Bus accessible." || echo "  (MPRIS not yet reachable — start AirPlay to activate it)"
import dbus
bus = dbus.SystemBus()
bus.get_object("org.mpris.MediaPlayer2.ShairportSync", "/org/mpris/MediaPlayer2")
PYEOF
    fi
else
    echo ""
    echo "  Service did not start — check:"
    echo "    journalctl -u shairport-sync -n 30 --no-pager"
fi

# ── done ──────────────────────────────────────────────────────────────────────
echo ""
echo "┌─────────────────────────────────────────────────────────┐"
echo "│  shairport-sync installed                               │"
echo "│                                                         │"
echo "│  AirPlay name : Mirror                                  │"
echo "│  Audio output : PipeWire (pipewire ALSA sink)           │"
echo "│  Running as   : $CURRENT_USER                                    │"
echo "│  MPRIS D-Bus  : org.mpris.MediaPlayer2.ShairportSync    │"
echo "│                                                         │"
echo "│  iPhone: Control Centre → AirPlay → Mirror              │"
echo "│  Music widget activates automatically when playing      │"
echo "│                                                         │"
echo "│  To rename: edit /etc/shairport-sync.conf → name =     │"
echo "│  Then: sudo systemctl restart shairport-sync            │"
echo "└─────────────────────────────────────────────────────────┘"
