#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Note on apk_obfuscation: moodle's APK is built by Cordova/Ionic and the bulk
# of the application code lives as JS/CSS bundles inside the WebView assets.
# R8 (the mechanism that gradle/obfuscate.init.gradle enables for other apps)
# only touches the thin Cordova native wrapper, so it has minimal effect here.
# The meaningful obfuscation for moodle is on the Angular side: we flip
# angular.json's production `optimization.scripts: false -> true` inside the
# Docker build when MCB_OBFUSCATE=1, which activates the dormant TerserPlugin
# that the upstream webpack.config.js already wires (with classname/fname kept
# so Angular DI continues to resolve). The patch step lives in Dockerfile.android.
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
