#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

git submodule update --init --recursive
sed -i.bak 's/signingConfigs\["O2Release"\]/signingConfigs.getByName("debug")/' main/build.gradle.kts

./gradlew :main:assembleUiOvpn2Release --no-daemon

cp main/build/outputs/apk/uiOvpn2/release/main-ui-ovpn2-universal-release.apk "$SCRIPT_DIR/unsigned.apk"
