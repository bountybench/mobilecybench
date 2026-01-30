#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase/SimpleLogin"

# Use debug signing (gradle provides internally) - app hardcodes keystore path
sed -i.bak 's/signingConfig signingConfigs.release/signingConfig signingConfigs.debug/' app/build.gradle

./gradlew --no-daemon assembleFdroidRelease

cp app/build/outputs/apk/fdroid/release/*.apk "$SCRIPT_DIR/unsigned.apk"
