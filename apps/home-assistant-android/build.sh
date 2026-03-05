#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

[[ -f "$SCRIPT_DIR/google-services.json" ]] && cp "$SCRIPT_DIR/google-services.json" app/google-services.json
[[ -f "$SCRIPT_DIR/google-services.json" ]] && cp "$SCRIPT_DIR/google-services.json" automotive/google-services.json
[[ -f "$SCRIPT_DIR/google-services.json" ]] && cp "$SCRIPT_DIR/google-services.json" wear/google-services.json

git submodule update --init --recursive

export KEYSTORE_PASSWORD="android"
export KEYSTORE_ALIAS="release"
export KEYSTORE_ALIAS_PASSWORD="android"

# Create mock keystores for each module if they don't exist (matching old setup_app_source.sh)
for module in app wear automotive; do
    KEYSTORE_FILE="$module/release_keystore.keystore"
    if [[ ! -f "$KEYSTORE_FILE" ]]; then
        echo "Creating release keystore for $module..."
        keytool -genkeypair -v \
            -keystore "$KEYSTORE_FILE" \
            -alias release \
            -keyalg RSA \
            -keysize 2048 \
            -validity 10000 \
            -storepass android \
            -keypass android \
            -dname "CN=Android Debug,O=Home Assistant,C=US"
    fi
done

# KEYSTORE_PATH must be an absolute path since Gradle resolves relative to each module
export KEYSTORE_PATH="$(pwd)/app/release_keystore.keystore"

./gradlew --no-daemon clean
./gradlew --no-daemon --max-workers=1 app:assembleMinimalRelease -Dorg.gradle.jvmargs="-Xmx2048m" -PnoLeakCanary

cp app/build/outputs/apk/minimal/release/app-minimal-release*.apk "$SCRIPT_DIR/unsigned.apk"
