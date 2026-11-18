# System install (packages):  make install DESTDIR="$pkgdir" PREFIX=/usr
# Per-user install:           ./install.sh  (wraps this with PREFIX=~/.local)

PREFIX       ?= /usr/local
BINDIR       ?= $(PREFIX)/bin
DATADIR      ?= $(PREFIX)/share
DOCDIR       ?= $(DATADIR)/doc/ghostty-tray
LICENSEDIR   ?= $(DATADIR)/licenses/ghostty-tray
# Starts the tray at login for every user; each user can turn it off in
# System Settings > Autostart.
AUTOSTARTDIR ?= /etc/xdg/autostart

all:

install:
	install -Dm755 ghostty-tray.py        "$(DESTDIR)$(BINDIR)/ghostty-tray"
	install -Dm644 ghostty-tray.desktop   "$(DESTDIR)$(DATADIR)/applications/ghostty-tray.desktop"
	install -Dm644 ghostty-tray.desktop   "$(DESTDIR)$(AUTOSTARTDIR)/ghostty-tray.desktop"
	install -Dm644 README.md              "$(DESTDIR)$(DOCDIR)/README.md"
	install -Dm644 -t "$(DESTDIR)$(DOCDIR)/examples/profiles" examples/profiles/*
	install -Dm644 LICENSE                "$(DESTDIR)$(LICENSEDIR)/LICENSE"

uninstall:
	rm -f  "$(DESTDIR)$(BINDIR)/ghostty-tray" \
	       "$(DESTDIR)$(DATADIR)/applications/ghostty-tray.desktop" \
	       "$(DESTDIR)$(AUTOSTARTDIR)/ghostty-tray.desktop" \
	       "$(DESTDIR)$(LICENSEDIR)/LICENSE"
	rm -rf "$(DESTDIR)$(DOCDIR)"
	-rmdir "$(DESTDIR)$(LICENSEDIR)" 2>/dev/null

.PHONY: all install uninstall
