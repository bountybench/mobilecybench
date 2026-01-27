#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

git submodule update --init --recursive

# Write keystore config (uses KEYSTORE_* env vars from build_apk.sh)
cat > gradle.properties <<EOF
keystoreO2File=$KEYSTORE_PATH
keystoreO2Password=$KEYSTORE_PASSWORD
keystoreO2Alias=$KEYSTORE_ALIAS
keystoreO2AliasPassword=$KEYSTORE_ALIAS_PASSWORD
android.useAndroidX=true
org.gradle.jvmargs=-Xmx4g -XX:MaxMetaspaceSize=1g -XX:+UseParallelGC
EOF

./gradlew :main:assembleUiOvpn2Release --no-daemon

cp main/build/outputs/apk/uiOvpn2/release/main-ui-ovpn2-universal-release.apk "$SCRIPT_DIR/unsigned.apk"
