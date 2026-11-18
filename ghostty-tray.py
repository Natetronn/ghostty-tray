#!/usr/bin/python3
"""System tray launcher for the Ghostty terminal (KDE Plasma).

Left click    open the selected profile (or toggle the quick terminal)
Middle click  toggle the quick terminal (or open a Default window when the
              quick terminal is already the left-click action)
Scroll        switch the selected profile
Right click   menu: profiles, open-once, icon style, quit

The tray icon talks to Plasma directly over D-Bus (StatusNotifierItem +
com.canonical.dbusmenu) instead of using QSystemTrayIcon, because Qt ignores
scroll events on tray icons. It registers with a stable Id, so it shows up in
System Tray Settings > Entries, where its visibility can be configured.

Profiles are Ghostty config files in ~/.config/ghostty/profiles/, loaded on
top of the main config with --config-file. Optional header comments:

    # name: Work            menu label (default: from the file name)
    # icon: utilities-terminal   theme icon name or image path for the tray
"""

import argparse
import html
import os
import re
import shutil
import signal
import sys
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

try:
    import dbus
    import dbus.service
    from dbus.mainloop.pyqt6 import DBusQtMainLoop
    from PyQt6.QtCore import (QFileSystemWatcher, QLockFile, QProcess, QProcessEnvironment,
                              QSettings, QSize, QTimer, QUrl)
    from PyQt6.QtGui import QDesktopServices, QGuiApplication, QIcon, QImage, QPainter
except ImportError as exc:
    sys.exit(f"ghostty-tray: missing Python module '{exc.name}'. "
             "Install python-dbus and python-pyqt6 for the system Python.")

__version__ = "0.1.0"

APP_ID = "ghostty-tray"
TITLE = "Ghostty Tray"
APP_ICON = "com.mitchellh.ghostty"
MONO_ICON = "utilities-terminal-symbolic"
CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
PROFILES_DIR = CONFIG_HOME / "ghostty" / "profiles"
PROFILE_SUFFIXES = {"", ".conf", ".config", ".ghostty"}
ICON_STYLES = {"color": "Color", "grayscale": "Grayscale", "monochrome": "Monochrome (follows theme)"}
PIXMAP_SIZES = (16, 22, 24, 32, 44, 48, 64, 96, 128)
SCROLL_STEP = 120  # one mouse-wheel notch

SNI_IFACE = "org.kde.StatusNotifierItem"
SNI_PATH = "/StatusNotifierItem"
WATCHER = "org.kde.StatusNotifierWatcher"
MENU_IFACE = "com.canonical.dbusmenu"
MENU_PATH = "/MenuBar"
PROPS_IFACE = "org.freedesktop.DBus.Properties"
GHOSTTY_BUS = "com.mitchellh.ghostty"
GHOSTTY_PATH = "/com/mitchellh/ghostty"


# ---------------------------------------------------------------- profiles

@dataclass(frozen=True)
class Profile:
    key: str          # settings key: file name in PROFILES_DIR, or a built-in key
    name: str
    icon: str = ""    # theme icon name or image path
    kind: str = "config"  # "default" (main config), "quick" (quick terminal), "config"

    @property
    def path(self) -> Path | None:
        return PROFILES_DIR / self.key if self.kind == "config" else None


# Built-in keys contain "/", so they can never collide with a profile file name.
DEFAULT_PROFILE = Profile("", "Default", kind="default")
QUICK_PROFILE = Profile("/quick-terminal", "Quick Terminal", kind="quick")
META_RE = re.compile(r"^\s*#\s*(name|icon)\s*:\s*(.+?)\s*$", re.IGNORECASE)


def read_profile(path: Path) -> Profile:
    meta: dict[str, str] = {}
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            for _, line in zip(range(30), f):
                if m := META_RE.match(line):
                    meta.setdefault(m.group(1).lower(), m.group(2))
    except OSError:
        pass
    name = meta.get("name") or path.stem.replace("-", " ").replace("_", " ").title()
    return Profile(path.name, name, meta.get("icon", ""))


def find_profiles() -> list[Profile]:
    files = []
    if PROFILES_DIR.is_dir():
        files = [p for p in PROFILES_DIR.iterdir()
                 if p.is_file() and not p.name.startswith(".") and p.suffix in PROFILE_SUFFIXES]
    profiles = sorted((read_profile(p) for p in files), key=lambda p: p.name.lower())
    return [DEFAULT_PROFILE, QUICK_PROFILE, *profiles]


# ------------------------------------------------------------------- icons

def resolve_icon(spec: str) -> tuple[str, QIcon]:
    """Map an icon spec to (theme icon name or "", QIcon), falling back to Ghostty's icon."""
    if spec:
        if "/" in spec or spec.startswith("~"):
            path = Path(spec).expanduser()
            if not path.is_absolute():
                path = PROFILES_DIR / path
            if path.is_file():
                return "", QIcon(str(path))
        elif QIcon.hasThemeIcon(spec):
            return spec, QIcon.fromTheme(spec)
    return APP_ICON, QIcon.fromTheme(APP_ICON, QIcon.fromTheme("utilities-terminal"))


def grayscale(image: QImage) -> QImage:
    """Grayscale copy of image that keeps its transparency."""
    src = image.convertToFormat(QImage.Format.Format_ARGB32)
    src.setDevicePixelRatio(1.0)
    out = src.convertToFormat(QImage.Format.Format_Grayscale8).convertToFormat(
        QImage.Format.Format_ARGB32_Premultiplied)
    painter = QPainter(out)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    painter.drawImage(0, 0, src)
    painter.end()
    return out


def argb32_be(image: QImage) -> bytes:
    """Pixels as ARGB32 in network byte order, as StatusNotifierItem expects."""
    img = image.convertToFormat(QImage.Format.Format_RGBA8888)
    ptr = img.constBits()
    ptr.setsize(img.sizeInBytes())
    rgba = bytes(ptr)
    argb = bytearray(len(rgba))
    argb[0::4], argb[1::4], argb[2::4], argb[3::4] = rgba[3::4], rgba[0::4], rgba[1::4], rgba[2::4]
    return bytes(argb)


def sni_pixmaps(icon: QIcon, gray: bool) -> dbus.Array:
    out = dbus.Array(signature="(iiay)")
    for size in PIXMAP_SIZES:
        image = icon.pixmap(QSize(size, size), 1.0).toImage()
        if image.isNull():
            continue
        if gray:
            image = grayscale(image)
        out.append(dbus.Struct((image.width(), image.height(), dbus.ByteArray(argb32_be(image))),
                               signature="iiay"))
    return out


# ----------------------------------------------------------- D-Bus objects

class PropertiesObject(dbus.service.Object):
    """dbus.service.Object with a read-only org.freedesktop.DBus.Properties."""

    IFACE = ""

    def properties(self) -> dict:
        raise NotImplementedError

    @dbus.service.method(PROPS_IFACE, in_signature="ss", out_signature="v")
    def Get(self, interface, name):
        props = self.properties()
        if interface != self.IFACE or name not in props:
            raise dbus.exceptions.DBusException(
                f"No such property {name}", name="org.freedesktop.DBus.Error.UnknownProperty")
        return props[name]

    @dbus.service.method(PROPS_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        return dbus.Dictionary(self.properties() if interface in (self.IFACE, "") else {},
                               signature="sv")

    @dbus.service.method(PROPS_IFACE, in_signature="ssv")
    def Set(self, interface, name, value):
        raise dbus.exceptions.DBusException(
            f"Property {name} is read-only", name="org.freedesktop.DBus.Error.PropertyReadOnly")

    @dbus.service.signal(PROPS_IFACE, signature="sa{sv}as")
    def PropertiesChanged(self, interface, changed, invalidated):
        pass


class StatusNotifierItem(PropertiesObject):
    IFACE = SNI_IFACE

    def __init__(self, bus, tray: "GhosttyTray"):
        super().__init__(bus, SNI_PATH)
        self.tray = tray

    def properties(self) -> dict:
        t = self.tray
        empty = dbus.Array(signature="(iiay)")
        return {
            "Category": "ApplicationStatus",
            "Id": APP_ID,
            "Title": TITLE,
            "Status": "Active",
            "WindowId": dbus.Int32(0),
            "IconName": t.icon_name,
            "IconPixmap": t.icon_pixmaps,
            "IconThemePath": "",
            "OverlayIconName": "",
            "OverlayIconPixmap": empty,
            "AttentionIconName": "",
            "AttentionIconPixmap": empty,
            "AttentionMovieName": "",
            "ToolTip": dbus.Struct((t.icon_name, t.icon_pixmaps, TITLE, t.tooltip_text()),
                                   signature="sa(iiay)ss"),
            "ItemIsMenu": False,
            "Menu": dbus.ObjectPath(MENU_PATH),
        }

    @dbus.service.method(SNI_IFACE, in_signature="ii")
    def Activate(self, x, y):
        QTimer.singleShot(0, self.tray.launch)

    @dbus.service.method(SNI_IFACE, in_signature="ii")
    def SecondaryActivate(self, x, y):
        QTimer.singleShot(0, self.tray.secondary)

    @dbus.service.method(SNI_IFACE, in_signature="ii")
    def ContextMenu(self, x, y):
        pass  # Plasma shows the exported dbusmenu itself

    @dbus.service.method(SNI_IFACE, in_signature="is")
    def Scroll(self, delta, orientation):
        self.tray.scroll(int(delta), str(orientation))

    @dbus.service.method(SNI_IFACE, in_signature="s")
    def ProvideXdgActivationToken(self, token):
        self.tray.activation_token = str(token)

    @dbus.service.signal(SNI_IFACE, signature="")
    def NewIcon(self):
        pass

    @dbus.service.signal(SNI_IFACE, signature="")
    def NewToolTip(self):
        pass

    @dbus.service.signal(SNI_IFACE, signature="")
    def NewTitle(self):
        pass

    @dbus.service.signal(SNI_IFACE, signature="s")
    def NewStatus(self, status):
        pass


@dataclass
class MenuNode:
    id: int
    props: dict
    children: list["MenuNode"] = field(default_factory=list)
    action: Callable[[], None] | None = None


class MenuBuilder:
    def __init__(self):
        self.root = MenuNode(0, {"children-display": "submenu"})
        self._stack = [self.root]
        self._next_id = 1

    def _add(self, props: dict, action=None) -> MenuNode:
        node = MenuNode(self._next_id, props, action=action)
        self._next_id += 1
        self._stack[-1].children.append(node)
        return node

    @staticmethod
    def _label(text: str, icon: str = "") -> dict:
        props = {"label": text.replace("_", "__")}  # "_" marks mnemonics in dbusmenu
        if icon:
            props["icon-name"] = icon
        return props

    def item(self, text, action, icon=""):
        self._add(self._label(text, icon), action)

    def radio(self, text, checked, action, icon=""):
        props = self._label(text, icon)
        props.update({"toggle-type": "radio", "toggle-state": dbus.Int32(1 if checked else 0)})
        self._add(props, action)

    def header(self, text):
        self._add({**self._label(text), "enabled": False})

    def separator(self):
        self._add({"type": "separator"})

    @contextmanager
    def submenu(self, text, icon=""):
        node = self._add({**self._label(text, icon), "children-display": "submenu"})
        self._stack.append(node)
        try:
            yield
        finally:
            self._stack.pop()


class DBusMenu(PropertiesObject):
    IFACE = MENU_IFACE

    def __init__(self, bus):
        super().__init__(bus, MENU_PATH)
        self.revision = 0
        self.nodes: dict[int, MenuNode] = {0: MenuNode(0, {"children-display": "submenu"})}

    def properties(self) -> dict:
        return {"Version": dbus.UInt32(3), "TextDirection": "ltr", "Status": "normal",
                "IconThemePath": dbus.Array([], signature="s")}

    def set_root(self, root: MenuNode) -> None:
        nodes, todo = {}, [root]
        while todo:
            node = todo.pop()
            nodes[node.id] = node
            todo.extend(node.children)
        self.nodes = nodes
        self.revision += 1
        self.LayoutUpdated(dbus.UInt32(self.revision), dbus.Int32(0))

    @staticmethod
    def _props(node: MenuNode, names) -> dbus.Dictionary:
        props = node.props if not names else {k: v for k, v in node.props.items() if k in names}
        return dbus.Dictionary(props, signature="sv")

    def _layout(self, node: MenuNode, depth: int, names) -> dbus.Struct:
        children = []
        if depth != 0:
            children = [self._layout(c, depth - 1 if depth > 0 else -1, names) for c in node.children]
        return dbus.Struct((dbus.Int32(node.id), self._props(node, names),
                            dbus.Array(children, signature="v")), signature="ia{sv}av")

    @dbus.service.method(MENU_IFACE, in_signature="iias", out_signature="u(ia{sv}av)")
    def GetLayout(self, parent_id, depth, names):
        node = self.nodes.get(int(parent_id))
        if node is None:
            raise dbus.exceptions.DBusException(f"Unknown menu item {parent_id}")
        return dbus.UInt32(self.revision), self._layout(node, int(depth), list(names))

    @dbus.service.method(MENU_IFACE, in_signature="aias", out_signature="a(ia{sv})")
    def GetGroupProperties(self, ids, names):
        wanted = [self.nodes[i] for i in ids if i in self.nodes] if ids else list(self.nodes.values())
        return dbus.Array([dbus.Struct((dbus.Int32(n.id), self._props(n, list(names))),
                                       signature="ia{sv}") for n in wanted],
                          signature="(ia{sv})")

    @dbus.service.method(MENU_IFACE, in_signature="is", out_signature="v")
    def GetProperty(self, item_id, name):
        node = self.nodes.get(int(item_id))
        if node is None or name not in node.props:
            raise dbus.exceptions.DBusException(f"No property {name} on item {item_id}")
        return node.props[name]

    def _event(self, item_id, event_id) -> bool:
        node = self.nodes.get(int(item_id))
        if node is None:
            return False
        if event_id == "clicked" and node.action:
            QTimer.singleShot(0, node.action)  # don't rebuild the menu inside the D-Bus call
        return True

    @dbus.service.method(MENU_IFACE, in_signature="isvu")
    def Event(self, item_id, event_id, data, timestamp):
        self._event(item_id, event_id)

    @dbus.service.method(MENU_IFACE, in_signature="a(isvu)", out_signature="ai")
    def EventGroup(self, events):
        return dbus.Array([e[0] for e in events if not self._event(e[0], e[1])], signature="i")

    @dbus.service.method(MENU_IFACE, in_signature="i", out_signature="b")
    def AboutToShow(self, item_id):
        return False

    @dbus.service.method(MENU_IFACE, in_signature="ai", out_signature="aiai")
    def AboutToShowGroup(self, ids):
        return dbus.Array([], signature="i"), dbus.Array([], signature="i")

    @dbus.service.signal(MENU_IFACE, signature="a(ia{sv})a(ias)")
    def ItemsPropertiesUpdated(self, updated, removed):
        pass

    @dbus.service.signal(MENU_IFACE, signature="ui")
    def LayoutUpdated(self, revision, parent):
        pass

    @dbus.service.signal(MENU_IFACE, signature="iu")
    def ItemActivationRequested(self, item_id, timestamp):
        pass


# -------------------------------------------------------------------- app

class GhosttyTray:
    def __init__(self, app: QGuiApplication, bus: dbus.Bus):
        self.app = app
        self.bus = bus
        self.settings = QSettings(APP_ID, APP_ID)
        self.ghostty = shutil.which("ghostty")
        self.systemd_run = shutil.which("systemd-run")
        self.activation_token = ""
        self._scroll_accum = 0
        self.profiles: list[Profile] = [DEFAULT_PROFILE]
        self.icon_name = APP_ICON
        self.icon_pixmaps = dbus.Array(signature="(iiay)")

        self.bus_name = dbus.service.BusName(f"org.kde.StatusNotifierItem-{os.getpid()}-1", bus)
        self.item = StatusNotifierItem(bus, self)
        self.menu = DBusMenu(bus)

        PROFILES_DIR.mkdir(parents=True, exist_ok=True)
        self.watcher = QFileSystemWatcher()
        self.watcher.directoryChanged.connect(self.schedule_reload)
        self.watcher.fileChanged.connect(self.schedule_reload)
        self.reload_timer = QTimer(singleShot=True, interval=250)
        self.reload_timer.timeout.connect(self.reload)
        self.reload()

        # Registers now, and again whenever plasmashell (the watcher) restarts.
        bus.watch_name_owner(WATCHER, self.on_watcher_owner)

    # ---- registration ---------------------------------------------------

    def on_watcher_owner(self, owner: str) -> None:
        if not owner:
            return
        self.bus.call_async(WATCHER, "/StatusNotifierWatcher", WATCHER,
                            "RegisterStatusNotifierItem", "s", (self.bus_name.get_name(),),
                            lambda *_: None,
                            lambda e: print(f"tray registration failed: {e}", file=sys.stderr))

    # ---- state ----------------------------------------------------------

    @property
    def selected(self) -> Profile:
        key = self.settings.value("profile", "", type=str)
        return next((p for p in self.profiles if p.key == key), DEFAULT_PROFILE)

    def select(self, profile: Profile) -> None:
        self.settings.setValue("profile", profile.key)
        self.refresh()

    @property
    def icon_style(self) -> str:
        style = self.settings.value("icon_style", "color", type=str)
        return style if style in ICON_STYLES else "color"

    def set_icon_style(self, style: str) -> None:
        self.settings.setValue("icon_style", style)
        self.refresh()

    def primary_label(self) -> str:
        p = self.selected
        return "Toggle Quick Terminal" if p.kind == "quick" else f"Open {p.name}"

    def secondary_action(self) -> tuple[str, Callable[[], None]]:
        """Middle-click: the quick terminal, unless that is already the left click."""
        if self.selected.kind == "quick":
            return "New Default Window", lambda: self.launch(DEFAULT_PROFILE)
        return "Toggle Quick Terminal", self.toggle_quick_terminal

    def secondary(self) -> None:
        self.secondary_action()[1]()

    def tooltip_text(self) -> str:
        return "<br>".join([
            f"Click: <b>{html.escape(self.primary_label())}</b>",
            f"Middle-click: {html.escape(self.secondary_action()[0])}",
            "Scroll: switch profile",
        ])

    def schedule_reload(self, *_):
        self.reload_timer.start()

    def reload(self) -> None:
        self.profiles = find_profiles()
        if files := self.watcher.files():
            self.watcher.removePaths(files)
        if PROFILES_DIR.is_dir() and not self.watcher.directories():
            self.watcher.addPath(str(PROFILES_DIR))
        paths = [str(p.path) for p in self.profiles if p.path]
        if paths:
            self.watcher.addPaths(paths)
        self.refresh()

    def refresh(self) -> None:
        self.update_icon()
        self.build_menu()

    def update_icon(self) -> None:
        style = self.icon_style
        if style == "monochrome" and QIcon.hasThemeIcon(MONO_ICON):
            name, pixmaps = MONO_ICON, dbus.Array(signature="(iiay)")
        elif style == "monochrome":
            # Icon theme lacks the symbolic icon: grayscale is the closest match.
            name, pixmaps = "", sni_pixmaps(resolve_icon("")[1], gray=True)
        else:
            theme_name, icon = resolve_icon(self.selected.icon)
            if style == "color" and theme_name:
                name, pixmaps = theme_name, dbus.Array(signature="(iiay)")
            else:
                name, pixmaps = "", sni_pixmaps(icon, gray=(style == "grayscale"))
        self.icon_name, self.icon_pixmaps = name, pixmaps
        self.item.NewIcon()
        self.item.NewToolTip()

    def build_menu(self) -> None:
        m = MenuBuilder()
        selected = self.selected

        def menu_icon(p: Profile) -> str:
            return p.icon if p.icon and "/" not in p.icon and QIcon.hasThemeIcon(p.icon) else ""

        quick_icon, window_icon = "utilities-terminal", "window-new"
        m.item(self.primary_label(), self.launch,
               icon=quick_icon if selected.kind == "quick" else window_icon)
        label, action = self.secondary_action()
        m.item(label, action, icon=window_icon if selected.kind == "quick" else quick_icon)
        m.separator()
        m.header("Click Opens")
        for p in self.profiles:
            m.radio(p.name, p.key == selected.key, lambda p=p: self.select(p), icon=menu_icon(p))
        with m.submenu("Open Once With", icon="window-duplicate"):
            for p in self.profiles:
                if p.kind != "quick":  # toggling isn't "opening"; it has its own item above
                    m.item(p.name, lambda p=p: self.launch(p), icon=menu_icon(p))
        m.separator()
        with m.submenu("Tray Icon", icon="preferences-desktop-icons"):
            for style, label in ICON_STYLES.items():
                m.radio(label, style == self.icon_style, lambda s=style: self.set_icon_style(s))
        m.item("Open Profiles Folder", self.open_profiles_folder, icon="folder-open")
        m.separator()
        m.item("Quit", self.app.quit, icon="application-exit")
        self.menu.set_root(m.root)

    # ---- input ----------------------------------------------------------

    def scroll(self, delta: int, orientation: str) -> None:
        if not orientation.lower().startswith("v") or len(self.profiles) < 2:
            return
        self._scroll_accum += delta
        steps = 0
        while abs(self._scroll_accum) >= SCROLL_STEP:
            step = -1 if self._scroll_accum > 0 else 1  # wheel down = next profile
            self._scroll_accum += SCROLL_STEP * step
            steps += step
        if steps:
            keys = [p.key for p in self.profiles]
            index = keys.index(self.selected.key) if self.selected.key in keys else 0
            self.select(self.profiles[(index + steps) % len(self.profiles)])

    # ---- actions --------------------------------------------------------

    def take_token(self) -> str:
        token, self.activation_token = self.activation_token, ""
        return token

    def launch(self, profile: Profile | None = None) -> None:
        profile = profile or self.selected
        if profile.kind == "quick":
            self.toggle_quick_terminal()
            return
        token = self.take_token()
        if profile.kind == "default":
            # Default: new window in the running (or D-Bus-activated) Ghostty.
            self.ghostty_action("new-window", token, on_error=lambda: self.spawn([], token))
        else:
            # CLI args make Ghostty start its own instance, which is what makes
            # the profile's config actually apply.
            self.spawn([f"--config-file={profile.path}", "--working-directory=home"], token)

    def toggle_quick_terminal(self) -> None:
        self.ghostty_action("toggle-quick-terminal", self.take_token(),
                            on_error=lambda: self.notify("Could not reach Ghostty over D-Bus."))

    def ghostty_action(self, action: str, token: str, on_error: Callable[[], None]) -> None:
        platform_data = {"activation-token": token, "desktop-startup-id": token} if token else {}

        def failed(err):
            print(f"ghostty action {action} failed: {err}", file=sys.stderr)
            on_error()

        self.bus.call_async(GHOSTTY_BUS, GHOSTTY_PATH, "org.gtk.Actions", "Activate", "sava{sv}",
                            (action, dbus.Array([], signature="v"),
                             dbus.Dictionary(platform_data, signature="sv")),
                            lambda *_: None, failed)

    def spawn(self, args: list[str], token: str) -> None:
        if not self.ghostty:
            self.notify("ghostty was not found on PATH.")
            return
        cmd = [self.ghostty, *args]
        if self.systemd_run:
            # Own scope, so the window survives the tray (or its service) stopping.
            cmd = [self.systemd_run, "--user", "--scope", "--collect", "--quiet",
                   "--slice=app.slice", f"--unit=app-ghostty-tray-{uuid.uuid4().hex[:8]}", *cmd]

        env = QProcessEnvironment.systemEnvironment()
        for var in ("TERM_PROGRAM", "TERM_PROGRAM_VERSION"):
            env.remove(var)  # would make Ghostty skip single-instance mode
        if token:
            env.insert("XDG_ACTIVATION_TOKEN", token)

        proc = QProcess()
        proc.setProgram(cmd[0])
        proc.setArguments(cmd[1:])
        proc.setProcessEnvironment(env)
        proc.setWorkingDirectory(str(Path.home()))
        ok, _pid = proc.startDetached()
        if not ok:
            self.notify("Failed to start Ghostty.")

    def open_profiles_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(PROFILES_DIR)))

    def notify(self, body: str) -> None:
        self.bus.call_async("org.freedesktop.Notifications", "/org/freedesktop/Notifications",
                            "org.freedesktop.Notifications", "Notify", "susssasa{sv}i",
                            (TITLE, dbus.UInt32(0), APP_ICON, TITLE, body,
                             dbus.Array([], signature="s"), dbus.Dictionary({}, signature="sv"), -1),
                            lambda *_: None, lambda *_: None)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ghostty-tray",
        description="System tray launcher for the Ghostty terminal (KDE Plasma). "
                    f"Profiles live in {PROFILES_DIR}.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser.parse_args()


def main() -> int:
    parse_args()
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    app = QGuiApplication(sys.argv[:1])
    app.setApplicationName(APP_ID)
    app.setDesktopFileName(APP_ID)
    app.setQuitOnLastWindowClosed(False)

    runtime = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
    lock = QLockFile(os.path.join(runtime, f"{APP_ID}.lock"))
    if not lock.tryLock(100):
        print("ghostty-tray is already running.", file=sys.stderr)
        return 0

    DBusQtMainLoop(set_as_default=True)
    bus = dbus.SessionBus()
    _tray = GhosttyTray(app, bus)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
