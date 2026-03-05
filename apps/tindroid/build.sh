#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

[[ -f "$SCRIPT_DIR/google-services.json" ]] && cp "$SCRIPT_DIR/google-services.json" app/google-services.json

# Create dummy keystore.properties (build.gradle reads it at config time)
cat > keystore.properties <<EOF
storeFile=dummy
storePassword=dummy
keyAlias=dummy
keyPassword=dummy
EOF

# Remove deprecated JVM option (not supported in Java 9+)
sed -i.bak 's/-XX:MaxPermSize=[0-9]*[kmgKMG]//g' gradle.properties
# Use debug signing
sed -i.bak 's/signingConfig signingConfigs.release/signingConfig signingConfigs.debug/' app/build.gradle

./gradlew assembleRelease --no-daemon

cp app/build/outputs/apk/release/*.apk "$SCRIPT_DIR/unsigned.apk"
