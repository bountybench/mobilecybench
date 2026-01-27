#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

# Initialize nested submodules
git submodule update --init --recursive

./gradlew clean
./gradlew assembleOriginalRelease --no-daemon

# Copy APK to standard location for root wrapper
cp owncloudApp/build/outputs/apk/original/release/*-original-release-unsigned.apk "$SCRIPT_DIR/unsigned.apk"
