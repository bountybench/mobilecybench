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

# Forward the repo-level gradle init script when build_apk.sh --obfuscate is in
# play. Upstream has no release minifyEnabled, so the init script flips it on
# for the release buildType (selector matches all flavors).
GRADLE_ARGS=()
if [ "${MCB_OBFUSCATE:-0}" = "1" ] && [ -n "${MCB_OBFUSCATE_INIT_SCRIPT:-}" ]; then
    GRADLE_ARGS+=(--init-script "$MCB_OBFUSCATE_INIT_SCRIPT")
fi

./gradlew --no-daemon "${GRADLE_ARGS[@]}" clean
./gradlew --no-daemon "${GRADLE_ARGS[@]}" --max-workers=1 ${GRADLE_EXTRA_ARGS:-} app:assembleFullRelease -Dorg.gradle.jvmargs="-Xmx2048m" -PnoLeakCanary

cp app/build/outputs/apk/full/release/app-full-release*.apk "$SCRIPT_DIR/unsigned.apk"
