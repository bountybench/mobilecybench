#!/bin/bash
set -e

echo "[Wallabag] Building wallabag Android app from source..."

if [ ! -d codebase ]; then
    echo "Error: codebase directory not found."
    exit 1
fi

cd codebase

export ANDROID_HOME="${ANDROID_HOME:-$HOME/.android-sdk}"
export PATH="$ANDROID_HOME/platform-tools:$PATH"

# Clean + build debug APK
./gradlew clean
./gradlew assembleDebug

APK_DIR="app/build/outputs/apk/debug"
APK_FILE="$APK_DIR/app-debug.apk"
if [ ! -f "$APK_FILE" ]; then
    echo "Error: APK not built!"
    exit 1
fi
cp "$APK_FILE" ../wallabag-debug.apk

echo "[Wallabag] APK built at wallabag-debug.apk"
