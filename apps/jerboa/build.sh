#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

./gradlew clean
./gradlew :app:assembleRelease --no-daemon

cp app/build/outputs/apk/release/*release-unsigned.apk "$SCRIPT_DIR/unsigned.apk"
