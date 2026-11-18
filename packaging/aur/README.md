# AUR packaging

These files are the contents of the separate AUR git repo
(`ssh://aur@aur.archlinux.org/ghostty-tray.git`).

Release steps:

1. Bump `__version__` in `ghostty-tray.py`, commit, tag `vX.Y.Z`, push the tag to GitHub.
2. Here: set `pkgver`, reset `pkgrel=1`, then
   ```sh
   updpkgsums                         # fills sha256sums from the GitHub tarball
   makepkg -si                        # test build + install
   makepkg --printsrcinfo > .SRCINFO
   ```
3. Copy `PKGBUILD`, `ghostty-tray.install` and `.SRCINFO` into the AUR repo, commit, push.

A fix to the packaging only (PKGBUILD or install script, same upstream
version): bump `pkgrel` instead, regenerate `.SRCINFO`, and push.
