#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

./gradlew --no-daemon \
    :AnkiDroid:assembleFullRelease \
    -x lint \
    -x :AnkiDroid:installGitHook

# Find universal or arm64 APK
APK_PATH=$(find AnkiDroid/build/outputs/apk/full/release -name "*-universal-*.apk" -type f 2>/dev/null | head -1)
if [[ -z "$APK_PATH" ]]; then
    APK_PATH=$(find AnkiDroid/build/outputs/apk/full/release -name "*-arm64-*.apk" -type f 2>/dev/null | head -1)
fi
if [[ -z "$APK_PATH" ]]; then
    APK_PATH=$(find AnkiDroid/build/outputs/apk/full/release -name "*.apk" -type f 2>/dev/null | head -1)
fi

cp "$APK_PATH" "$SCRIPT_DIR/unsigned.apk"
