#!/usr/bin/env bash
# Remove a per-user install made by install.sh.
# Profiles in ~/.config/ghostty/profiles and settings in ~/.config/ghostty-tray are kept.
set -euo pipefail
cd "$(dirname "$0")"

DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}"

systemctl --user disable --now ghostty-tray.service 2>/dev/null || true
pkill -f "$HOME/.local/bin/ghostty-tray" 2>/dev/null || true
make --no-print-directory uninstall \
    PREFIX="$HOME/.local" DATADIR="$DATA" USERUNITDIR="$DATA/systemd/user"
rm -f "$CONFIG/systemd/user/ghostty-tray.service" "$CONFIG/autostart/ghostty-tray.desktop"
systemctl --user daemon-reload
echo "Removed. Profiles and settings were kept."
