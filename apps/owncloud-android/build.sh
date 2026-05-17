#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

# Initialize nested submodules
git submodule update --init --recursive

GRADLE_ARGS=()
if [ "${MCB_OBFUSCATE:-0}" = "1" ] && [ -n "${MCB_OBFUSCATE_INIT_SCRIPT:-}" ]; then
    GRADLE_ARGS+=(--init-script "$MCB_OBFUSCATE_INIT_SCRIPT")
fi

./gradlew "${GRADLE_ARGS[@]}" clean
./gradlew "${GRADLE_ARGS[@]}" assembleOriginalRelease --no-daemon

# Copy APK to standard location for root wrapper
cp owncloudApp/build/outputs/apk/original/release/*-original-release-unsigned.apk "$SCRIPT_DIR/unsigned.apk"
