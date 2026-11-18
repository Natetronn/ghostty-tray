# Ghostty Tray

A KDE Plasma system tray icon for the [Ghostty](https://ghostty.org) terminal.

| Input        | Action                                               |
| ------------ | ---------------------------------------------------- |
| Left click   | Open the selected profile, or toggle the quick terminal          |
| Middle click | Toggle the quick terminal (or open a Default window if the quick terminal is the left-click action) |
| Scroll       | Switch the selected profile                                      |
| Right click  | Menu: pick profile, open once with another, icon style, quit     |

The icon appears in **System Tray Settings → Entries** as *Ghostty Tray*, where
it can be set to *Shown when relevant*, *Always shown*, *Always hidden* or
*Disabled*. It must be running to be listed there.

## Install

**Arch / CachyOS (AUR):**

```sh
yay -S ghostty-tray        # or paru, etc.
systemctl --user enable --now ghostty-tray.service
```

**From source, per user (no root):**

```sh
./install.sh      # installs to ~/.local, enables + starts the user service
./uninstall.sh    # removes it (keeps your profiles and settings)
```

**From source, system-wide:** `sudo make install PREFIX=/usr`, then enable the
user service as above.

It runs as the systemd user service `ghostty-tray.service`, which starts with
the Plasma session and restarts if it crashes. **Quit** in the menu stops it
until next login; start it again from the app launcher (*Ghostty Tray*) or with
`systemctl --user start ghostty-tray`. Logs: `journalctl --user -u ghostty-tray`.

Requirements (all in the Arch repos): `ghostty`, `python-pyqt6`, `python-dbus`.
Wayland is needed for the quick terminal (a Ghostty limitation).

## Profiles

A profile is a Ghostty config file in `~/.config/ghostty/profiles/`. It is
loaded **on top of** `~/.config/ghostty/config`, so it only needs the settings
it changes. Example profiles ship in `examples/profiles/` (installed to
`/usr/share/doc/ghostty-tray/examples/profiles/` by the package).

Optional header comments:

```ini
# name: Work                      menu label (default: from the file name)
# icon: utilities-terminal        tray icon while selected: theme icon name or image path
font-size = 14
background-opacity = 1.0
```

The menu updates automatically when files are added, renamed or edited.

Two entries are always present:

- **Default** opens a window in the already-running Ghostty (via D-Bus), so it
  shares that instance and its quick terminal.
- **Quick Terminal** makes left click show/hide Ghostty's drop-down terminal
  (`toggle_quick_terminal`); middle click then opens a Default window instead.

Each profile file starts a separate Ghostty instance, since Ghostty only reads
config at startup. Each runs in its own systemd scope, so windows stay open if
the tray stops.

## Icon styles

*Tray Icon* in the menu: **Color**, **Grayscale**, or **Monochrome**, which uses
the theme's symbolic terminal icon and follows the panel's light/dark colors.

## Settings

Stored in `~/.config/ghostty-tray/ghostty-tray.conf` (selected profile and icon style).

## How it works

Instead of Qt's `QSystemTrayIcon`, which ignores scroll events, the app
implements the `org.kde.StatusNotifierItem` and `com.canonical.dbusmenu` D-Bus
interfaces itself with `dbus-python`. Plasma draws the icon and menu. Ghostty's
quick terminal and new windows are triggered through its
`org.gtk.Actions` D-Bus interface (`com.mitchellh.ghostty`).

## License

MIT, see [LICENSE](LICENSE).
