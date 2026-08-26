# Packaging Bookwork

Builds a standalone desktop app (no separately-installed Python/uv needed to
run it) with [PyInstaller](https://pyinstaller.org/), from `bookwork.spec`.

## Build

From the repo root, with dependencies already synced (`uv sync`):

```bash
uv run pyinstaller packaging/bookwork.spec --noconfirm
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

## Known gaps (see DESIGN.md §6/§7)

- No app icon yet (`packaging/bookwork.spec`'s `icon=` is a TODO for the
  macOS bundle; Windows/Linux icon wiring isn't set up either).
- No code signing/notarization — needed before distributing outside your
  own machine on Windows (SmartScreen warning) or macOS (Gatekeeper).
- Only ever actually built and run on Linux so far. The spec is written to
  be cross-platform-correct (windowed mode, `argv_emulation` and a proper
  `.app` bundle on macOS), but Windows/macOS builds need to be run and
  smoke-tested on those OSes before calling them done.
