#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

./gradlew assembleOseRelease --no-daemon

# Copy APK to standard location (already signed by gradle)
cp app/build/outputs/apk/ose/release/davx5-ose-*-release.apk "$SCRIPT_DIR/unsigned.apk"
