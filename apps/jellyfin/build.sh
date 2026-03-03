#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

./gradlew clean
./gradlew assembleLibreRelease --no-daemon

# Copy unsigned APK to standard location for root wrapper
APK=$(find app/build/outputs/apk/libre/release/ -name '*libre*release-unsigned.apk' -type f | head -1)
if [[ -z "$APK" ]]; then
    echo "ERROR: No unsigned APK found after build" >&2
    exit 1
fi
cp "$APK" "$SCRIPT_DIR/unsigned.apk"
