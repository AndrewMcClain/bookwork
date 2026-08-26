# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller build spec for Bookwork. Build with (from the repo root):
#
#     uv run pyinstaller packaging/bookwork.spec --noconfirm
#
# Produces a onedir bundle at dist/bookwork/ (dist/bookwork.app on macOS).
# This spec is written to be correct on Windows/macOS/Linux alike, but has
# only actually been built and smoke-tested on Linux — see DESIGN.md and
# README.md for the Windows/macOS build/verify steps still needed.

import sys

a = Analysis(
    ["../src/bookwork/__main__.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="bookwork",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # windowed: no terminal popup on Windows, no Dock console on macOS
    disable_windowed_traceback=False,
    # macOS: lets the app receive "open with" / drag-onto-Dock-icon file
    # events as argv, same as double-clicking a PDF associated with it. A
    # no-op on Windows/Linux.
    argv_emulation=(sys.platform == "darwin"),
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="bookwork",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Bookwork.app",
        icon=None,  # TODO: add an .icns app icon
        bundle_identifier="com.bookwork.app",
        info_plist={
            "CFBundleName": "Bookwork",
            "CFBundleDisplayName": "Bookwork",
            "CFBundleShortVersionString": "0.1.0",
            "NSHighResolutionCapable": True,
        },
    )
