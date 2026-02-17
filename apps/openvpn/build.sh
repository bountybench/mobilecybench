#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

# Generate keystore for release signing if it doesn't exist (before entering codebase)
KEYSTORE_PATH="$(pwd)/keystore.jks"
if [ ! -f "$KEYSTORE_PATH" ]; then
    echo "Generating release keystore..."
    keytool -genkey -v -keystore "$KEYSTORE_PATH" \
        -alias openvpn-release \
        -keyalg RSA \
        -keysize 2048 \
        -validity 10000 \
        -storepass android123 \
        -keypass android123 \
        -dname "CN=OpenVPN Release,OU=Development,O=OpenVPN,L=City,S=State,C=US" \
        -noprompt
fi

# Create gradle.properties with signing config for releaseOvpn2 using absolute path
cat > gradle.properties <<EOF
android.useAndroidX=true
android.enableJetifier=true
android.nonFinalResIds=false
org.gradle.jvmargs=-Xmx2048m -XX:MaxMetaspaceSize=512m -XX:+HeapDumpOnOutOfMemoryError
org.gradle.daemon=true
keystoreO2File=$KEYSTORE_PATH
keystoreO2Password=android123
keystoreO2Alias=openvpn-release
keystoreO2AliasPassword=android123
EOF

git submodule update --init --recursive

./gradlew clean
./gradlew :main:assembleUiOvpn2Release

RELEASE_APK="main/build/outputs/apk/uiOvpn2/release/main-ui-ovpn2-universal-release.apk"
cp "$RELEASE_APK" "$SCRIPT_DIR/unsigned.apk"

