#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

git submodule update --init --recursive

./gradlew clean
./gradlew :main:assembleUiOvpn2Release

RELEASE_APK="main/build/outputs/apk/uiOvpn2/release/main-ui-ovpn2-universal-release.apk"
cp "$RELEASE_APK" "$SCRIPT_DIR/unsigned.apk"

