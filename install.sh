#!/usr/bin/env bash
# Install ghostty-tray for the current user as a systemd user service.
set -euo pipefail
cd "$(dirname "$0")"

BIN="$HOME/.local/bin"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
UNITS="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
AUTOSTART="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
PROFILES="${XDG_CONFIG_HOME:-$HOME/.config}/ghostty/profiles"

install -Dm755 ghostty-tray.py "$BIN/ghostty-tray"
install -Dm644 ghostty-tray.desktop "$APPS/ghostty-tray.desktop"
install -Dm644 ghostty-tray.service "$UNITS/ghostty-tray.service"

# Older versions used an autostart entry; the service replaces it.
rm -f "$AUTOSTART/ghostty-tray.desktop"

# Seed example profiles only if the user has none yet.
mkdir -p "$PROFILES"
if [ -z "$(ls -A "$PROFILES")" ]; then
    cp examples/profiles/* "$PROFILES/"
fi

# Stop a copy started outside the service, then (re)start the service.
pkill -f "$BIN/ghostty-tray" 2>/dev/null || true
systemctl --user daemon-reload
systemctl --user enable ghostty-tray.service
systemctl --user restart ghostty-tray.service
systemctl --user --no-pager --lines=0 status ghostty-tray.service
