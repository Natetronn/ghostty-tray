# System install (packages):  make install DESTDIR="$pkgdir" PREFIX=/usr
# Per-user install:           ./install.sh  (wraps this with PREFIX=~/.local)

PREFIX      ?= /usr/local
BINDIR      ?= $(PREFIX)/bin
DATADIR     ?= $(PREFIX)/share
USERUNITDIR ?= $(PREFIX)/lib/systemd/user
DOCDIR      ?= $(DATADIR)/doc/ghostty-tray
LICENSEDIR  ?= $(DATADIR)/licenses/ghostty-tray

all: ghostty-tray.service

ghostty-tray.service: ghostty-tray.service.in
	sed 's|@BINDIR@|$(BINDIR)|g' $< > $@

install: ghostty-tray.service
	install -Dm755 ghostty-tray.py        "$(DESTDIR)$(BINDIR)/ghostty-tray"
	install -Dm644 ghostty-tray.desktop   "$(DESTDIR)$(DATADIR)/applications/ghostty-tray.desktop"
	install -Dm644 ghostty-tray.service   "$(DESTDIR)$(USERUNITDIR)/ghostty-tray.service"
	install -Dm644 README.md              "$(DESTDIR)$(DOCDIR)/README.md"
	install -Dm644 -t "$(DESTDIR)$(DOCDIR)/examples/profiles" examples/profiles/*
	install -Dm644 LICENSE                "$(DESTDIR)$(LICENSEDIR)/LICENSE"

uninstall:
	rm -f  "$(DESTDIR)$(BINDIR)/ghostty-tray" \
	       "$(DESTDIR)$(DATADIR)/applications/ghostty-tray.desktop" \
	       "$(DESTDIR)$(USERUNITDIR)/ghostty-tray.service" \
	       "$(DESTDIR)$(LICENSEDIR)/LICENSE"
	rm -rf "$(DESTDIR)$(DOCDIR)"
	-rmdir "$(DESTDIR)$(LICENSEDIR)" 2>/dev/null

clean:
	rm -f ghostty-tray.service

.PHONY: all install uninstall clean
