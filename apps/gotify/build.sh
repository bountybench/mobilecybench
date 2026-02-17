#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

./gradlew --no-daemon --max-workers=1 :app:assembleRelease -x test -x lint -x check

APK_PATH=$(find . -type f -path "*/build/outputs/apk/**/release/*-universal-*.apk" 2>/dev/null | head -1)
if [[ -z "$APK_PATH" ]]; then
    APK_PATH=$(find . -type f -path "*/build/outputs/apk/**/release/*arm64-v8a*-release.apk" 2>/dev/null | head -1)
fi
if [[ -z "$APK_PATH" ]]; then
    APK_PATH=$(find . -type f -path "*/build/outputs/apk/**/release/*-release.apk" 2>/dev/null | head -1)
fi
if [[ -z "$APK_PATH" ]]; then
    APK_PATH=$(find . -type f -path "*/build/outputs/apk/release/*.apk" 2>/dev/null | head -1)
fi

cp "$APK_PATH" "$SCRIPT_DIR/unsigned.apk"
