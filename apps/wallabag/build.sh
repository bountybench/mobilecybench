#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

./gradlew clean
./gradlew assembleRelease --no-daemon

cp app/build/outputs/apk/release/app-release-unsigned.apk "$SCRIPT_DIR/unsigned.apk"
