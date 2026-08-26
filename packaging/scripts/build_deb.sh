#!/bin/bash
# Build a .deb package for Bookwork from the PyInstaller onedir bundle.
#
# Uses dpkg-deb directly (part of every Debian/Ubuntu system) rather than a
# separate tool like fpm, so this has no extra build-time dependency beyond
# what's already needed to build/run Bookwork itself.
#
# Usage (from anywhere):
#   packaging/scripts/build_deb.sh
#
# Rebuilds the PyInstaller bundle first, then stages a package tree and
# calls dpkg-deb --build. Output: packaging/dist/bookwork_<version>_<arch>.deb
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGING_DIR="$(dirname "$SCRIPT_DIR")"
REPO_ROOT="$(dirname "$PACKAGING_DIR")"

VERSION="$(grep -m1 '^version = ' "$REPO_ROOT/pyproject.toml" | sed -E 's/version = "(.*)"/\1/')"
ARCH="$(dpkg --print-architecture)"

echo "==> Building Bookwork $VERSION ($ARCH)"

echo "==> Running PyInstaller"
(
    cd "$PACKAGING_DIR"
    uv run --project "$REPO_ROOT" pyinstaller bookwork.spec --noconfirm
)

BUNDLE_DIR="$PACKAGING_DIR/dist/bookwork"
if [ ! -x "$BUNDLE_DIR/bookwork" ]; then
    echo "error: expected PyInstaller output at $BUNDLE_DIR/bookwork, not found" >&2
    exit 1
fi

STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT

echo "==> Staging package tree in $STAGING"
mkdir -p \
    "$STAGING/DEBIAN" \
    "$STAGING/opt/bookwork" \
    "$STAGING/usr/bin" \
    "$STAGING/usr/share/applications" \
    "$STAGING/usr/share/doc/bookwork"

# The whole onedir bundle (binary + _internal/) lives under /opt, matching
# how most bundled-runtime Linux apps (e.g. browsers) are laid out -- it's
# not meant to be picked apart by the package manager the way a
# distro-built package's individual libs would be.
cp -a "$BUNDLE_DIR/." "$STAGING/opt/bookwork/"

# A relative symlink (../../opt/bookwork/bookwork) rather than absolute, so
# it resolves correctly regardless of dpkg's install root (relevant for
# e.g. a chroot/sysroot build, not just a plain `dpkg -i`).
ln -s ../../opt/bookwork/bookwork "$STAGING/usr/bin/bookwork"

cp "$PACKAGING_DIR/linux/bookwork.desktop" "$STAGING/usr/share/applications/bookwork.desktop"
cp "$PACKAGING_DIR/linux/copyright" "$STAGING/usr/share/doc/bookwork/copyright"

INSTALLED_SIZE="$(du -sk "$STAGING" | cut -f1)"
sed \
    -e "s/@VERSION@/$VERSION/" \
    -e "s/@ARCH@/$ARCH/" \
    -e "s/@INSTALLED_SIZE@/$INSTALLED_SIZE/" \
    "$PACKAGING_DIR/linux/control.in" > "$STAGING/DEBIAN/control"

cp "$PACKAGING_DIR/linux/postinst" "$STAGING/DEBIAN/postinst"
cp "$PACKAGING_DIR/linux/postrm" "$STAGING/DEBIAN/postrm"

# dpkg-deb doesn't enforce permissions itself; set them explicitly so the
# built package doesn't depend on whatever the build machine's umask
# happened to be.
find "$STAGING" -type d -exec chmod 755 {} +
find "$STAGING" -type f -exec chmod 644 {} +
chmod 755 "$STAGING/opt/bookwork/bookwork" "$STAGING/DEBIAN/postinst" "$STAGING/DEBIAN/postrm"

OUT_PATH="$PACKAGING_DIR/dist/bookwork_${VERSION}_${ARCH}.deb"
echo "==> Building $OUT_PATH"
dpkg-deb --root-owner-group --build "$STAGING" "$OUT_PATH"

echo "==> Done: $OUT_PATH"
dpkg-deb --info "$OUT_PATH"
