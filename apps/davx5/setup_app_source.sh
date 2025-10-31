#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
APK_PATH="${SCRIPT_DIR}/codebase/app/build/outputs/apk/ose/release/davx5-ose-4.4.11-ose-release.apk"
source "$ROOT_DIR/utils/android.sh"

cd "$SCRIPT_DIR"

create_signature() {
    export ANDROID_KEYSTORE="${SCRIPT_DIR}/keys/davx5-release.keystore"
    export ANDROID_KEYSTORE_PASSWORD="xxJ78n4i2"
    export ANDROID_KEY_ALIAS="davx5-key"
    export ANDROID_KEY_PASSWORD="xxJ78n4i2"

    if [ ! -f "$ANDROID_KEYSTORE" ]; then
        mkdir -p "$(dirname "${ANDROID_KEYSTORE}")"
        keytool -genkey -v -keystore "${ANDROID_KEYSTORE}" \
                -alias "${ANDROID_KEY_ALIAS}" -keyalg RSA -keysize 2048 \
                -storepass "${ANDROID_KEYSTORE_PASSWORD}" \
                -keypass "${ANDROID_KEY_PASSWORD}" \
                -dname "CN=Test, O=Test, C=US"
    fi
}

build_apk() {
    cd codebase
    ./gradlew assembleOseRelease
}

main() {
    create_signature
    build_apk

    mkdir -p "${SCRIPT_DIR}/apk"
    cp "${APK_PATH}" "${SCRIPT_DIR}/apk/davx5.apk" 
}

main "$@"