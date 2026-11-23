#!/bin/bash
# Build macos/out/Facet-<version>-<commit>.dmg from the committed tree (HEAD) plus the built client.
# Needs: Apple silicon, the Xcode Command Line Tools (swift, codesign, hdiutil) and a built client
# (cd client && npm run build). Downloads a pinned Python, uv and ExifTool, verified by checksum.
set -euo pipefail

PBS_RELEASE=20261026
PBS_PYTHON=3.12.16
PBS_SHA256=353d5f1b4fd2715e7053f12f068435d5bbad16b91e057006b5d01e0925709a7e
UV_VERSION=0.13.7
UV_SHA256=81b811b57e4624df7ed3aac148e0359100d9962f3d9dce00aec533dc2e086731
# Same pin as the Dockerfile: 13.23-13.27 corrupt darktable XMP sidecars.
EXIFTOOL_VERSION=13.55
EXIFTOOL_SHA256=5c9d422ad128fab728aacc5cc0aa77095d14cde74931389dd961d3d720e6b316
MIN_MACOS=15.0
BUNDLE_ID=io.github.ncoevoet.facet

MACOS_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$MACOS_DIR")"
OUT="$MACOS_DIR/out"
DOWNLOADS="$OUT/downloads"
DIST="$REPO/client/dist/client/browser"
# Stage outside the repo: a dev viewer (`python viewer.py`, auto-reload) watches it for .py changes.
WORK="$(mktemp -d "${TMPDIR:-/tmp}/facet-app-build.XXXXXX")"
APP="$WORK/Facet.app"
CONTENTS="$APP/Contents"
RESOURCES="$CONTENTS/Resources"

die() { echo "error: $*" >&2; exit 1; }

[ "$(uname -m)" = arm64 ] || die "Facet.app is built for Apple silicon (arm64) only"
[ -f "$DIST/index.html" ] || die "build the client first (cd client && npm run build): $DIST"
if [ -n "$(git -C "$REPO" status --porcelain -- . ':!macos/out')" ]; then
    echo "warning: uncommitted changes are NOT in the app (it packages HEAD)" >&2
fi

VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$REPO/pyproject.toml" | head -1)"
COMMIT="$(git -C "$REPO" rev-parse --short HEAD)"
BRANCH="$(git -C "$REPO" rev-parse --abbrev-ref HEAD)"
LABEL_COMMIT="$COMMIT"
if [ "$BRANCH" = HEAD ]; then
    # A detached checkout has no branch: name a pull-request build after its branch and head commit.
    if [ -n "${GITHUB_HEAD_REF:-}" ]; then
        BRANCH="$GITHUB_HEAD_REF"
        if [ -n "${PR_HEAD_SHA:-}" ]; then LABEL_COMMIT="${PR_HEAD_SHA:0:7}"; fi
    else
        BRANCH="$(git -C "$REPO" tag --points-at HEAD | head -1)"
    fi
    [ -n "$BRANCH" ] || BRANCH=detached
fi

# fetch URL SHA256 NAME: download once into $DOWNLOADS, verify every time.
fetch() {
    local file="$DOWNLOADS/$3"
    mkdir -p "$DOWNLOADS"
    if [ ! -f "$file" ]; then
        curl -fL --retry 3 --proto '=https' -o "$file.part" "$1"
        mv "$file.part" "$file"
    fi
    echo "$2  $file" | shasum -a 256 -c --quiet - || { rm -f "$file"; die "checksum mismatch: $1"; }
}

fetch "https://github.com/astral-sh/python-build-standalone/releases/download/$PBS_RELEASE/cpython-$PBS_PYTHON%2B$PBS_RELEASE-aarch64-apple-darwin-install_only_stripped.tar.gz" \
    "$PBS_SHA256" "python-$PBS_PYTHON-$PBS_RELEASE.tar.gz"
fetch "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/uv-aarch64-apple-darwin.tar.gz" \
    "$UV_SHA256" "uv-$UV_VERSION.tar.gz"
fetch "https://github.com/exiftool/exiftool/archive/refs/tags/$EXIFTOOL_VERSION.tar.gz" \
    "$EXIFTOOL_SHA256" "exiftool-$EXIFTOOL_VERSION.tar.gz"

echo "==> Building the launcher"
swift build -c release --package-path "$MACOS_DIR/Launcher"
LAUNCHER="$(swift build -c release --package-path "$MACOS_DIR/Launcher" --show-bin-path)/Facet"

echo "==> Staging Facet.app"
mkdir -p "$CONTENTS/MacOS" "$RESOURCES/bin" "$RESOURCES/exiftool" "$RESOURCES/app"
cp "$LAUNCHER" "$CONTENTS/MacOS/Facet"
tar -xzf "$DOWNLOADS/python-$PBS_PYTHON-$PBS_RELEASE.tar.gz" -C "$RESOURCES"
tar -xzf "$DOWNLOADS/uv-$UV_VERSION.tar.gz" -C "$WORK" uv-aarch64-apple-darwin/uv
mv "$WORK/uv-aarch64-apple-darwin/uv" "$RESOURCES/bin/uv"
tar -xzf "$DOWNLOADS/exiftool-$EXIFTOOL_VERSION.tar.gz" -C "$RESOURCES/exiftool" --strip-components=1 \
    "exiftool-$EXIFTOOL_VERSION/exiftool" "exiftool-$EXIFTOOL_VERSION/lib"

# App files: the committed tree, minus what a running install never reads.
git -C "$REPO" archive --format=tar HEAD | tar -xf - -C "$RESOURCES/app"
for path in client tests .claude .github bench build-tools installer macos/Launcher \
            docs/de docs/es docs/fr docs/it docs/pt docs/zh; do
    rm -rf "${RESOURCES:?}/app/$path"
done
mkdir -p "$RESOURCES/app/client/dist/client"
cp -R "$DIST" "$RESOURCES/app/client/dist/client/browser"
# The user menu shows this beside the version (FACET_BUILD), as the Docker image and the MSI do.
echo "$BRANCH@$LABEL_COMMIT" > "$RESOURCES/app/macos/build-label.txt"
echo "Facet $VERSION, commit $COMMIT, built $(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$RESOURCES/app/BUILD.txt"
find "$APP" \( -name __pycache__ -o -name .DS_Store \) -prune -exec rm -rf {} +
# The interpreter imports encodings before any flag or script can stop it writing bytecode, and
# a write inside the signed bundle breaks its seal: ship the stdlib compiled, never re-checked.
"$RESOURCES/python/bin/python3" -I -m compileall -q -j 0 --invalidation-mode unchecked-hash \
    "$RESOURCES/python/lib/python$(echo "$PBS_PYTHON" | cut -d. -f1-2)"

ICONSET="$WORK/AppIcon.iconset"
mkdir -p "$ICONSET"
for size in 16 32 128 256 512; do
    sips -z "$size" "$size" "$REPO/docs/logo-512.png" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
    if [ "$size" -lt 512 ]; then  # no 512@2x: the source is 512 px
        sips -z $((size * 2)) $((size * 2)) "$REPO/docs/logo-512.png" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
    fi
done
iconutil -c icns "$ICONSET" -o "$RESOURCES/AppIcon.icns"
rm -rf "$ICONSET"

cat > "$CONTENTS/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleDevelopmentRegion</key><string>en</string>
    <key>CFBundleDisplayName</key><string>Facet</string>
    <key>CFBundleExecutable</key><string>Facet</string>
    <key>CFBundleIconFile</key><string>AppIcon</string>
    <key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
    <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
    <key>CFBundleLocalizations</key>
    <array><string>en</string><string>de</string><string>es</string><string>fr</string><string>it</string><string>pt</string><string>zh-Hans</string></array>
    <key>CFBundleName</key><string>Facet</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>$VERSION</string>
    <key>CFBundleVersion</key><string>$VERSION</string>
    <key>LSApplicationCategoryType</key><string>public.app-category.photography</string>
    <key>LSMinimumSystemVersion</key><string>$MIN_MACOS</string>
    <key>LSUIElement</key><true/>
    <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST
plutil -lint "$CONTENTS/Info.plist" >/dev/null

echo "==> Signing (ad hoc)"
# Inside out: every Mach-O first, then the bundle, which seals everything else.
find "$RESOURCES" -type f -print0 | while IFS= read -r -d '' file; do
    if file -b "$file" | grep -q '^Mach-O'; then
        # pipefail keeps codesign's failure; only its "replacing existing signature" note is dropped.
        codesign --force --sign - --timestamp=none "$file" 2>&1 | { grep -v 'replacing existing signature' || true; } >&2
    fi
done
codesign --force --sign - --timestamp=none "$APP"

echo "==> Checking the bundled tools"
# After signing: a run that wrote anything into the bundle fails the verify below.
FACET_HOME="$WORK/smoke" "$RESOURCES/python/bin/python3" -I "$RESOURCES/app/macos/facet_mac.py" env >/dev/null
"$RESOURCES/python/bin/python3" -c 'import json, sqlite3, ssl, hashlib'
"$RESOURCES/bin/uv" --version
"$RESOURCES/exiftool/exiftool" -ver
minos="$(vtool -show-build "$CONTENTS/MacOS/Facet" | awk '/minos/ {print $2; exit}')"
[ "$minos" = "$MIN_MACOS" ] || die "launcher minos is $minos, expected $MIN_MACOS"
rm -rf "$WORK/smoke"
codesign --verify --deep --strict "$APP"

echo "==> Building the disk image"
DMG_ROOT="$WORK/dmg"
mkdir -p "$DMG_ROOT" "$OUT"
mv "$APP" "$DMG_ROOT/Facet.app"
ln -s /Applications "$DMG_ROOT/Applications"
DMG="$OUT/Facet-$VERSION-$COMMIT.dmg"
rm -f "$DMG"
make_dmg() { hdiutil create -volname Facet -srcfolder "$DMG_ROOT" -format ULFO -ov "$DMG" >/dev/null; }
# hdiutil sometimes fails with "Resource busy" while Spotlight looks at the new volume.
make_dmg || { sleep 3; make_dmg; }
rm -rf "$WORK"
echo "$DMG ($(du -h "$DMG" | cut -f1))"
