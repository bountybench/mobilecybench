#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

[[ -f "$SCRIPT_DIR/google-services.json" ]] && cp "$SCRIPT_DIR/google-services.json" app/google-services.json
[[ -f "$SCRIPT_DIR/google-services.json" ]] && cp "$SCRIPT_DIR/google-services.json" automotive/google-services.json
[[ -f "$SCRIPT_DIR/google-services.json" ]] && cp "$SCRIPT_DIR/google-services.json" wear/google-services.json

git submodule update --init --recursive

./gradlew --no-daemon clean
./gradlew --no-daemon --max-workers=1 app:assembleMinimalRelease -Dorg.gradle.jvmargs="-Xmx2048m" -PnoLeakCanary

cp app/build/outputs/apk/minimal/release/app-minimal-release*.apk "$SCRIPT_DIR/unsigned.apk"
