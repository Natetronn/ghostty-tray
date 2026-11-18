#!/usr/bin/env bash
# Per-user install without root: ~/.local plus an autostart entry.
# For a system-wide install use the AUR package (or `sudo make install PREFIX=/usr`).
set -euo pipefail
cd "$(dirname "$0")"

DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}"
PROFILES="$CONFIG/ghostty/profiles"

if [ -e /usr/bin/ghostty-tray ]; then
    echo "ghostty-tray is already installed system-wide (/usr/bin/ghostty-tray)." >&2
    exit 1
fi

make --no-print-directory install \
    PREFIX="$HOME/.local" DATADIR="$DATA" AUTOSTARTDIR="$CONFIG/autostart"

# Seed example profiles only if the user has none yet.
mkdir -p "$PROFILES"
if [ -z "$(ls -A "$PROFILES")" ]; then
    cp examples/profiles/* "$PROFILES/"
fi

# Start it now (a running copy re-execs itself when its file is replaced).
if ! pgrep -f "$HOME/.local/bin/ghostty-tray" >/dev/null; then
    setsid -f "$HOME/.local/bin/ghostty-tray" >/dev/null 2>&1
fi
echo "Installed. Ghostty Tray is running and will start at every login."
