#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

git submodule update --init --recursive

./gradlew clean
./gradlew assembleFdroidRelease --no-daemon

cp app/build/outputs/apk/fdroid/release/*-fdroid-release-unsigned.apk "$SCRIPT_DIR/unsigned.apk"
