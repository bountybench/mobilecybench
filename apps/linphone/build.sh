#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

# Patch gradle.properties for low memory
if [[ -f "gradle.properties" ]]; then
    sed -i.bak \
        -e 's/^org.gradle.jvmargs=.*/org.gradle.jvmargs=-Xmx4g -XX:MaxMetaspaceSize=1g -XX:+UseParallelGC -Dfile.encoding=UTF-8/' \
        -e '/^org.gradle.parallel/d' \
        gradle.properties
    grep -q '^org.gradle.parallel=false' gradle.properties || echo 'org.gradle.parallel=false' >> gradle.properties
fi

# Patch build.gradle.kts for all ABIs and debug signing
sed -i.bak 's/abiFilters += listOf("armeabi-v7a", "arm64-v8a")/abiFilters += listOf("armeabi-v7a", "arm64-v8a", "x86", "x86_64")/' app/build.gradle.kts
sed -i.bak 's/signingConfigs.getByName("release")/signingConfigs.getByName("debug")/' app/build.gradle.kts

./gradlew assembleRelease --no-daemon --max-workers=1

# Find the release APK
APK_PATH=$(find app/build/outputs/apk/release -name "*.apk" -type f 2>/dev/null | head -1)

cp "$APK_PATH" "$SCRIPT_DIR/unsigned.apk"

./gradlew --stop || true
