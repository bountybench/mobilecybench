#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

./gradlew clean -Dorg.gradle.jvmargs="-Xmx4G -XX:MaxMetaspaceSize=1G"
./gradlew assembleLibreRelease --no-daemon -Dorg.gradle.jvmargs="-Xmx4G -XX:MaxMetaspaceSize=1G"

APK_PATH=$(find app/build/outputs/apk/libre/release -name "*universal*release*.apk" -type f 2>/dev/null | head -1)
if [[ -z "$APK_PATH" ]]; then
    APK_PATH=$(find app/build/outputs/apk/libre/release -name "*release*.apk" -type f 2>/dev/null | head -1)
fi

cp "$APK_PATH" "$SCRIPT_DIR/unsigned.apk"
