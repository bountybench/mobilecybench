#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

# Create keystore.properties for signing
cat > keystore.properties <<EOF
storeFile=debug.keystore
storePassword=android
keyAlias=androiddebugkey
keyPassword=android
EOF

# Create debug keystore if missing
if [[ ! -f "app/debug.keystore" ]]; then
    keytool -genkey -v -keystore app/debug.keystore \
        -alias androiddebugkey -keyalg RSA -keysize 2048 \
        -validity 10000 -storepass android -keypass android \
        -dname "CN=Android Debug, O=Android, C=US"
fi

# Copy google-services.json
if [[ -f "$SCRIPT_DIR/google-services.json" ]]; then
    cp "$SCRIPT_DIR/google-services.json" app/google-services.json
fi

# Patch gradle.properties for Java 17 compatibility
if [[ -f "gradle.properties" ]] && grep -q "MaxPermSize" gradle.properties; then
    sed -i.bak 's/-XX:MaxPermSize=[0-9]*[kmgKMG]//g' gradle.properties
fi

./gradlew --stop || true
./gradlew clean
./gradlew assembleRelease --no-daemon

cp app/build/outputs/apk/release/*.apk "$SCRIPT_DIR/unsigned.apk"
