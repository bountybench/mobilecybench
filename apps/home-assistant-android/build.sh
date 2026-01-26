#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

# Copy google-services.json
if [[ -f "$SCRIPT_DIR/google-services.json" ]]; then
    cp "$SCRIPT_DIR/google-services.json" app/google-services.json
    cp "$SCRIPT_DIR/google-services.json" automotive/google-services.json
    cp "$SCRIPT_DIR/google-services.json" wear/google-services.json
else
    echo "ERROR: google-services.json not found in $SCRIPT_DIR"
    exit 1
fi

# Generate mock keystores if missing
for module in app wear automotive; do
    if [[ ! -f "$module/release_keystore.keystore" ]]; then
        keytool -genkeypair -v -keystore "$module/release_keystore.keystore" \
            -alias release -keyalg RSA -keysize 2048 -validity 10000 \
            -storepass android -keypass android \
            -dname "CN=Android Debug,O=Home Assistant,C=US"
    fi
done

export KEYSTORE_PASSWORD="android"
export KEYSTORE_ALIAS="release"
export KEYSTORE_ALIAS_PASSWORD="android"

git submodule update --init --recursive

./gradlew --no-daemon clean
./gradlew --no-daemon --max-workers=1 \
    app:assembleMinimalRelease \
    -Dorg.gradle.jvmargs="-Xmx2048m" \
    -Dorg.gradle.parallel=false \
    -PnoLeakCanary

cp app/build/outputs/apk/minimal/release/app-minimal-release.apk "$SCRIPT_DIR/unsigned.apk"
