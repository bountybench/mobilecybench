#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

# Create gradle.properties with signing config using env vars from build_apk.sh
cat > gradle.properties <<EOF
android.useAndroidX=true
android.enableJetifier=true
android.nonFinalResIds=false
org.gradle.jvmargs=-Xmx2048m -XX:MaxMetaspaceSize=512m -XX:+HeapDumpOnOutOfMemoryError
org.gradle.daemon=true
keystoreO2File=${KEYSTORE_PATH:-dummy}
keystoreO2Password=${KEYSTORE_PASSWORD:-dummy}
keystoreO2Alias=${KEYSTORE_ALIAS:-dummy}
keystoreO2AliasPassword=${KEYSTORE_ALIAS_PASSWORD:-dummy}
EOF

# Initialize submodules (OpenVPN native libs)
git submodule update --init --recursive

./gradlew clean --no-daemon
./gradlew :main:assembleUiOvpn2Release --no-daemon

# Copy unsigned APK to standard location (prefer universal APK to support all ABIs including x86_64 CI emulators)
APK=$(find main/build/outputs/apk/uiOvpn2/release -name "*universal*.apk" -type f | head -1)
if [[ -z "$APK" ]]; then
    APK=$(find main/build/outputs/apk/uiOvpn2/release -name "*.apk" -type f | head -1)
fi
if [[ -z "$APK" ]]; then
    echo "ERROR: No APK found after build" >&2
    find main/build/outputs -name "*.apk" -type f 2>/dev/null | head -5 >&2
    exit 1
fi
cp "$APK" "$SCRIPT_DIR/unsigned.apk"
