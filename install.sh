#!/usr/bin/env bash
# Per-user install without root: ~/.local plus a systemd user service.
# For a system-wide install use the AUR package (or `make install PREFIX=/usr`).
set -euo pipefail
cd "$(dirname "$0")"

DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}"
UNITDIR="$DATA/systemd/user"
PROFILES="$CONFIG/ghostty/profiles"

if [ -e /usr/bin/ghostty-tray ]; then
    echo "ghostty-tray is already installed system-wide (/usr/bin/ghostty-tray)." >&2
    echo "Use: systemctl --user enable --now ghostty-tray.service" >&2
    exit 1
fi

# Earlier versions put the unit in ~/.config/systemd/user and used autostart.
if [ -f "$CONFIG/systemd/user/ghostty-tray.service" ]; then
    systemctl --user disable ghostty-tray.service 2>/dev/null || true
    rm -f "$CONFIG/systemd/user/ghostty-tray.service"
fi
rm -f "$CONFIG/autostart/ghostty-tray.desktop"

make --no-print-directory install \
    PREFIX="$HOME/.local" DATADIR="$DATA" USERUNITDIR="$UNITDIR"
make --no-print-directory clean

# Seed example profiles only if the user has none yet.
mkdir -p "$PROFILES"
if [ -z "$(ls -A "$PROFILES")" ]; then
    cp examples/profiles/* "$PROFILES/"
fi

# Stop a copy started outside the service, then (re)start the service.
pkill -f "$HOME/.local/bin/ghostty-tray" 2>/dev/null || true
systemctl --user daemon-reload
systemctl --user enable ghostty-tray.service
systemctl --user restart ghostty-tray.service
systemctl --user --no-pager --lines=0 status ghostty-tray.service
