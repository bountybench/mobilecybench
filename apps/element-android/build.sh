#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

./gradlew clean
./gradlew assembleFdroidRustCryptoRelease --no-daemon -PallWarningsAsErrors=false ${GRADLE_EXTRA_ARGS:-}

# Copy universal APK to standard location for root wrapper
cp vector-app/build/outputs/apk/fdroidRustCrypto/release/vector-fdroid-rustCrypto-universal-release*.apk "$SCRIPT_DIR/unsigned.apk"
