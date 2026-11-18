#!/usr/bin/env bash
# Remove a per-user install made by install.sh.
# Profiles in ~/.config/ghostty/profiles and settings in ~/.config/ghostty-tray are kept.
set -euo pipefail
cd "$(dirname "$0")"

DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}"

pkill -f "$HOME/.local/bin/ghostty-tray" 2>/dev/null || true
make --no-print-directory uninstall \
    PREFIX="$HOME/.local" DATADIR="$DATA" AUTOSTARTDIR="$CONFIG/autostart"
echo "Removed. Profiles and settings were kept."
