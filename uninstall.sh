#!/usr/bin/env bash
# Remove ghostty-tray. Profiles in ~/.config/ghostty/profiles are kept.
set -euo pipefail
UNITS="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

systemctl --user disable --now ghostty-tray.service 2>/dev/null || true
pkill -f "$HOME/.local/bin/ghostty-tray" 2>/dev/null || true
rm -f "$HOME/.local/bin/ghostty-tray" \
      "$UNITS/ghostty-tray.service" \
      "${XDG_DATA_HOME:-$HOME/.local/share}/applications/ghostty-tray.desktop" \
      "${XDG_CONFIG_HOME:-$HOME/.config}/autostart/ghostty-tray.desktop"
systemctl --user daemon-reload
echo "Removed. Profiles in ~/.config/ghostty/profiles and settings in ~/.config/ghostty-tray were kept."
