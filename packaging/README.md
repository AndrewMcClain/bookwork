# Packaging Bookwork

Builds a standalone desktop app (no separately-installed Python/uv needed to
run it) with [PyInstaller](https://pyinstaller.org/), from `bookwork.spec`.

## Build

With dependencies already synced (`uv sync`), from the `packaging/` directory
(the spec's relative paths, and its output location, are resolved against the
current directory, not the spec file's location — running this from the repo
root instead puts the build in the repo root's own `dist/`, mixed in with
`uv build`'s wheel/sdist output):

```bash
cd packaging
uv run pyinstaller bookwork.spec --noconfirm
```

Output goes to `dist/` next to the spec (i.e. `packaging/dist/`):

- **Linux**: `packaging/dist/bookwork/bookwork` — a onedir bundle; run the
  `bookwork` binary inside it. Built and smoke-tested here.
- **Windows**: `packaging/dist/bookwork/bookwork.exe`, same onedir layout.
  **Not yet built or tested** — needs to be run on an actual Windows
  machine; the spec is written to be correct there but is unverified.
- **macOS**: `packaging/dist/Bookwork.app`. **Not yet built or tested** —
  needs an actual Mac; also unverified, and unsigned/unnotarized (Gatekeeper
  will refuse to open it without at least right-click → Open, and won't be
  distributable outside your own machine without a Developer ID + notarization).

## Verifying a build

Smoke-test that the binary actually launches and can open a PDF, e.g. on
Linux/macOS:

```bash
QT_QPA_PLATFORM=offscreen ./packaging/dist/bookwork/bookwork some.pdf
```

(drop `QT_QPA_PLATFORM=offscreen` when you have a real display attached — it
forces a headless Qt backend, useful for CI or a bare SSH session). On
Windows, just run `bookwork.exe` from a terminal or double-click it; drop a
PDF onto it or use File → Open.

## Linux: building a .deb

```bash
packaging/scripts/build_deb.sh
```

Rebuilds the PyInstaller bundle, then stages and builds
`packaging/dist/bookwork_<version>_<arch>.deb` — using `dpkg-deb` directly
(part of every Debian/Ubuntu system) rather than a separate tool like `fpm`,
so this has no extra build-time dependency.

Layout, matching how most bundled-runtime Linux apps (e.g. browsers) are
packaged rather than picked apart into individual distro-managed libs:

- The whole onedir bundle installs to `/opt/bookwork/`.
- `/usr/bin/bookwork` is a relative symlink into it.
- `/usr/share/applications/bookwork.desktop` registers it as a PDF-opening
  app in the desktop menu/file-open dialogs (no icon yet — see Known gaps).
- `/usr/share/doc/bookwork/copyright` carries the Debian-format copyright
  file (GPL v3).
- `postinst`/`postrm` refresh the desktop database (best-effort; a no-op if
  `desktop-file-utils` isn't installed).

Source files for all of the above live in `packaging/linux/`.

**Verifying a build** (without installing it system-wide):

```bash
DEB=packaging/dist/bookwork_0.1.0_amd64.deb
dpkg-deb --info "$DEB"       # metadata (control file, Depends, size)
dpkg-deb --contents "$DEB"   # full file listing + permissions
dpkg-deb -x "$DEB" /tmp/bw-test && QT_QPA_PLATFORM=offscreen /tmp/bw-test/opt/bookwork/bookwork
```

An actual `sudo dpkg -i` install (which exercises `postinst`/`postrm` and the
real `/usr/bin` symlink resolution) hasn't been done here — extraction plus
directly running the bundled binary is the safe-by-default way to verify the
package tree and confirm the binary itself launches; do the real install
when you're ready to actually use it, or in a disposable container/VM.

**Runtime dependencies (`Depends:`)**: intentionally conservative — set to
just `libc6, libx11-6, libxcb1, libdbus-1-3, libfontconfig1`, the base
libraries virtually guaranteed present on any Linux desktop system, with
names that have been stable across Debian/Ubuntu releases for a long time.
The bundled Qt actually links a much longer transitive list at runtime
(checked via `ldd` against `_internal/PySide6/Qt/plugins/platforms/libqxcb.so`
in a built bundle) — things like `libxkbcommon-x11-0`, `libxcb-cursor0`,
`libgl1`, `libegl1`, `libglib2.0-0` (renamed `libglib2.0-0t64` on newer
Ubuntu releases due to the 64-bit `time_t` transition) — deliberately left
out of `Depends:` because their exact package names vary across distro
releases in a way that risks the package becoming *uninstallable* on some
release rather than just missing a soft dependency. In practice these are
already present on essentially any system with a graphical desktop
environment (they're pulled in transitively by other desktop software), so
this hasn't been an issue when actually launching the built bundle — but if
`bookwork` ever fails to start elsewhere with an "error while loading shared
libraries" message, that's the likely list to check with `apt install`.

## Known gaps

- No app icon yet (`packaging/bookwork.spec`'s `icon=` is a TODO for the
  macOS bundle; the `.deb`'s desktop entry and Windows icon wiring have the
  same gap — deliberately deferred, see below).
- No code signing/notarization — needed before distributing outside your
  own machine on Windows (SmartScreen warning) or macOS (Gatekeeper).
- No native installer yet for Windows (`.msi`/`.exe` via WiX/NSIS) or macOS
  (`.dmg`/`.pkg`) — only the raw PyInstaller bundle. Linux has a `.deb` (see
  above); Windows/macOS builds also still need to be run and smoke-tested on
  those actual OSes before calling any of this done (only ever built and run
  on Linux so far — the spec is written to be cross-platform-correct:
  windowed mode, `argv_emulation` and a proper `.app` bundle on macOS).
- The `.deb`'s package metadata has a couple of placeholders worth revisiting
  once they have real values: no `Homepage:` field (no public repo URL yet),
  and `Maintainer:` is Andrew McClain's personal email (fine for a
  single-maintainer project, but worth a project-specific address if that
  ever changes).
