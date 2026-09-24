#!/bin/sh
# Build a Debian package of Ear Link. Run from anywhere.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
VERSION=1.0.0
STAGE=$(mktemp -d)
cleanup() { rm -rf "$STAGE"; }
trap cleanup EXIT

mkdir -p \
  "$STAGE/DEBIAN" \
  "$STAGE/usr/bin" \
  "$STAGE/usr/lib/python3/dist-packages/earlink" \
  "$STAGE/usr/share/applications" \
  "$STAGE/usr/share/icons/hicolor/scalable/apps"

cat > "$STAGE/DEBIAN/control" << EOF
Package: earlink
Version: ${VERSION}
Section: sound
Priority: optional
Architecture: all
Depends: python3 (>= 3.11), python3-gi, python3-dbus, gir1.2-gtk-4.0, gir1.2-adw-1, bluez
Recommends: pipewire-pulse | pulseaudio-utils
Maintainer: Ear Link <earlink@localhost>
Description: companion for Nothing and CMF earbuds
 Ear Link scans for Nothing and CMF earbuds, pairs them over Bluetooth,
 and controls the earbud features that talk to the buds directly: noise
 cancellation, equalizer, gestures, battery, low latency, in-ear detection,
 find-my-earbuds, fit test, bass enhance, spatial audio, and Super Mic.
EOF

cp "$ROOT"/earlink/*.py "$STAGE/usr/lib/python3/dist-packages/earlink/"
cp "$ROOT/packaging/earlink.desktop" "$STAGE/usr/share/applications/earlink.desktop"
cp "$ROOT/packaging/earlink.svg" "$STAGE/usr/share/icons/hicolor/scalable/apps/earlink.svg"

cat > "$STAGE/usr/bin/earlink" << 'EOF'
#!/usr/bin/python3
from earlink.ui import main

raise SystemExit(main())
EOF
chmod 0755 "$STAGE/usr/bin/earlink"
chmod 0755 "$STAGE" "$STAGE/usr" "$STAGE/usr/bin" "$STAGE/usr/lib" "$STAGE/usr/share"

OUT="$ROOT/../earlink_${VERSION}_all.deb"
dpkg-deb --root-owner-group --build "$STAGE" "$OUT"
echo "$OUT"
