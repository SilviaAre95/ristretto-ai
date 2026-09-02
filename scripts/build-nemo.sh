#!/usr/bin/env bash
# Build Nemo.app — the desktop face of Ristretto.
#
# A hand-rolled bundle rather than an Xcode project: the whole app is one
# Swift file, and a .xcodeproj would be more machinery than software. The
# bundle itself is not optional, though — macOS will not grant a microphone
# to a bare executable, because TCC has no identity to attribute it to.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
out="${NEMO_OUT:-$repo/build}"
app="$out/Nemo.app"

command -v swiftc >/dev/null 2>&1 || {
  echo "build-nemo: swiftc not found — install the Xcode command line tools" >&2
  exit 1
}

rm -rf "$app"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
cp "$repo/nemo/Info.plist" "$app/Contents/Info.plist"

swiftc -O \
  -framework AppKit -framework AVFoundation \
  -o "$app/Contents/MacOS/Nemo" \
  "$repo/nemo/Nemo.swift"

# Ad-hoc signature. Unsigned bundles are refused the microphone on current
# macOS; ad-hoc is enough for a local tool and needs no developer account.
codesign --force --sign - "$app" >/dev/null 2>&1 || {
  echo "build-nemo: could not sign the bundle; the microphone may be refused" >&2
}

echo "built: $app"
echo "  run:  open $app        (or: $app/Contents/MacOS/Nemo for logs)"
echo "  dash: ${RIS_DASH:-http://127.0.0.1:8787}"
