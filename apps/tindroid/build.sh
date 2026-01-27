#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

[[ -f "$SCRIPT_DIR/google-services.json" ]] && cp "$SCRIPT_DIR/google-services.json" app/google-services.json
sed -i.bak 's/signingConfig signingConfigs.release/signingConfig signingConfigs.debug/' app/build.gradle

./gradlew assembleRelease --no-daemon

cp app/build/outputs/apk/release/*.apk "$SCRIPT_DIR/unsigned.apk"
