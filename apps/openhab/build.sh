#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

# Patch gradle.properties for memory
if [[ -f "gradle.properties" ]]; then
    sed -i.bak '/^org\.gradle\.jvmargs=/d' gradle.properties
    sed -i.bak '/^org\.gradle\.configuration-cache=/d' gradle.properties
    echo "org.gradle.jvmargs=-Xmx4g" >> gradle.properties
    echo "org.gradle.configuration-cache=false" >> gradle.properties
fi

./gradlew :mobile:clean :mobile:assembleFullStableRelease --no-daemon -x lint -x lintVitalFullStableRelease -x uploadCrashlyticsMappingFileFullStableRelease

# Find the release APK
APK_PATH=$(find mobile/build/outputs/apk -type f \( -name "*release.apk" -o -name "*release-unsigned.apk" \) 2>/dev/null | head -1)

cp "$APK_PATH" "$SCRIPT_DIR/unsigned.apk"

# Restore gradle.properties
if [[ -f "gradle.properties.bak" ]]; then
    mv gradle.properties.bak gradle.properties
fi
