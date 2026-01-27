#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Auto-accept corepack downloads (no interactive prompt)
export COREPACK_ENABLE_DOWNLOAD_PROMPT=0

# Uninstall global react-native-cli to avoid conflicts
npm uninstall -g react-native-cli @react-native-community/cli 2>/dev/null || true

# Apply SDK patch if exists
if [[ -f "$SCRIPT_DIR/sdk34.patch" ]]; then
    cd "$SCRIPT_DIR/codebase"
    git apply "$SCRIPT_DIR/sdk34.patch" 2>/dev/null || true
    cd "$SCRIPT_DIR"
fi

# Install only app-mobile and its dependencies (not desktop/cli/server)
cd "$SCRIPT_DIR/codebase"
npm install -g yarn 2>/dev/null || true
yarn workspaces focus @joplin/app-mobile

cd packages/app-mobile

cd android

# Patch gradle.properties for memory
if [[ -f "gradle.properties" ]]; then
    sed -i.bak \
        -e 's/^org.gradle.jvmargs=.*/org.gradle.jvmargs=-Xmx4096m -XX:MaxMetaspaceSize=1024m -XX:+UseParallelGC -Dfile.encoding=UTF-8 -Xss4m/' \
        -e '/^org.gradle.parallel/d' \
        gradle.properties
    grep -q '^org.gradle.parallel=false' gradle.properties || echo 'org.gradle.parallel=false' >> gradle.properties
fi

# Use debug signing (app hardcodes release keystore path)
sed -i.bak 's/signingConfig signingConfigs.release/signingConfig signingConfigs.debug/' app/build.gradle

./gradlew assembleRelease --no-daemon --max-workers=1

cp app/build/outputs/apk/release/app-release.apk "$SCRIPT_DIR/unsigned.apk"
