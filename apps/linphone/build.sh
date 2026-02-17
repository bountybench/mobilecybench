#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

# ABI patch for emulator + debug signing (app hardcodes keystore path)
sed -i.bak -e 's/abiFilters += listOf("armeabi-v7a", "arm64-v8a")/abiFilters += listOf("armeabi-v7a", "arm64-v8a", "x86", "x86_64")/' \
           -e 's/signingConfigs.getByName("release")/signingConfigs.getByName("debug")/' app/build.gradle.kts

./gradlew assembleRelease --no-daemon --max-workers=1

cp "$(find app/build/outputs/apk/release -name "*.apk" -type f | head -1)" "$SCRIPT_DIR/unsigned.apk"
