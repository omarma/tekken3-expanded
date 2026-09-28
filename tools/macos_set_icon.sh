#!/bin/bash
# Give the built executable a Finder icon on macOS.
#
#   tools/macos_set_icon.sh <icon.png|icon.icns> <executable>
#
# A bare Unix executable has nowhere to keep an icon, so Finder draws the
# generic one. The icon therefore goes into the file's resource fork, which
# lives in extended attributes: the executable's own bytes are not touched and
# it keeps running exactly as before.
#
# This is cosmetic. If the tools are missing the build must not fail, so the
# script warns and returns success. It is driven from CMakeLists.txt when
# TEKKEN3_MACOS_ICON names an image; no artwork is shipped with this
# repository.
set -euo pipefail

SOURCE="${1:?usage: macos_set_icon.sh <icon.png|icon.icns> <executable>}"
TARGET="${2:?usage: macos_set_icon.sh <icon.png|icon.icns> <executable>}"

warn() { echo "macos_set_icon: $*, leaving the default icon in place" >&2; exit 0; }

[ "$(uname -s)" = "Darwin" ] || warn "not macOS"
[ -f "$SOURCE" ] || warn "no such icon: $SOURCE"
[ -f "$TARGET" ] || warn "no such executable: $TARGET"

for tool in sips iconutil DeRez Rez SetFile; do
    command -v "$tool" >/dev/null 2>&1 || warn "$tool is missing (install the Xcode command line tools)"
done

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

case "$SOURCE" in
*.icns)
    cp "$SOURCE" "$WORK/icon.icns"
    ;;
*)
    # iconutil wants every slot from 16 to 512, each with its @2x variant.
    mkdir "$WORK/icon.iconset"
    for size in 16 32 128 256 512; do
        sips -z "$size" "$size" "$SOURCE" \
            --out "$WORK/icon.iconset/icon_${size}x${size}.png" >/dev/null 2>&1 \
            || warn "sips could not read $SOURCE"
        sips -z "$((size * 2))" "$((size * 2))" "$SOURCE" \
            --out "$WORK/icon.iconset/icon_${size}x${size}@2x.png" >/dev/null 2>&1 \
            || warn "sips could not read $SOURCE"
    done
    iconutil -c icns "$WORK/icon.iconset" -o "$WORK/icon.icns" \
        || warn "iconutil could not build an icns from $SOURCE"
    ;;
esac

# sips -i puts the icns into the file's own icon resource, which DeRez can then
# read back as the resource that Finder looks for.
sips -i "$WORK/icon.icns" >/dev/null 2>&1 || warn "sips could not stage the icns"
DeRez -only icns "$WORK/icon.icns" > "$WORK/icon.rsrc" || warn "DeRez failed"

# Replacing an earlier icon rather than appending to it keeps repeated builds
# from stacking resources in the fork.
xattr -d com.apple.ResourceFork "$TARGET" 2>/dev/null || true
Rez -append "$WORK/icon.rsrc" -o "$TARGET" || warn "Rez failed"
SetFile -a C "$TARGET" || warn "SetFile failed"
