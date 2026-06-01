#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Moodle ships most of its meaningful application logic as Angular bundles
# inside the WebView assets. R8 mostly affects the thin Cordova wrapper, so the
# obfuscation path here is app-specific: Dockerfile.android flips Angular
# production `optimization.scripts` on when MCB_OBFUSCATE=1.
DOCKER_BUILD_ARGS=()
if [ "${MCB_OBFUSCATE:-0}" = "1" ]; then
    DOCKER_BUILD_ARGS+=(--build-arg "MCB_OBFUSCATE=1")
fi

# Build using Docker
docker build --platform linux/amd64 "${DOCKER_BUILD_ARGS[@]}" -t moodle-builder -f Dockerfile.android .

# Extract APK from container
docker rm -f temp-builder 2>/dev/null || true
docker create --name temp-builder moodle-builder
docker cp temp-builder:/moodleapp/platforms/android/app/build/outputs/apk/release/app-release-unsigned.apk "$SCRIPT_DIR/unsigned.apk"
docker rm temp-builder
