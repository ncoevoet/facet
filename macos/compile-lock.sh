#!/bin/sh
# Resolve macos/requirements.in for the app's interpreter and platform, hash-pinned.
# The shared locks are constraints, so every version they pin is the version the
# Windows and Docker builds test. opencv-python is left out: it and
# opencv-python-headless install into the same cv2/ folder (see install.sh step 9),
# and the app needs only the headless build. The test-only pytest plugins are left out
# too (pytest itself stays: pyiqa imports it).
set -eu
cd "$(dirname "$0")"
TARGET="--python-version 3.12 --python-platform aarch64-apple-darwin"
# The app's minimum macOS (LSMinimumSystemVersion); onnxruntime 1.27 needs 14 or later.
# --no-config: a personal uv.toml (index, exclude-newer) must not change the committed lock.
MACOSX_DEPLOYMENT_TARGET=15.0 uv pip compile --no-config requirements.in \
    -c ../requirements.lock.txt -c ../requirements.restricted.lock.txt $TARGET \
    --generate-hashes --no-annotate --no-header --quiet \
    --no-emit-package opencv-python --no-emit-package pytest-asyncio \
    --no-emit-package pytest-timeout --no-emit-package pytest-xdist --no-emit-package execnet \
    -o requirements.lock.txt "$@"
# What the source-only packages (filterpy, openai-clip, reverse-geocoder) need to build, at
# the lock's own versions, so setup checks a hash for every file it downloads.
printf 'setuptools\nnumpy\n' | uv pip compile --no-config - -c requirements.lock.txt $TARGET \
    --generate-hashes --no-annotate --no-header --quiet -o build-constraints.txt
