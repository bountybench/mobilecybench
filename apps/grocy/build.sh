#!/bin/bash
#
# Grocy Android - Build Script
#
# This script only handles the build. Environment setup, signing, and
# output handling are done by the root build_apk.sh wrapper.
#
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

# Memory optimization for CI
if [[ -f "gradle.properties" ]]; then
    sed -i.bak \
        -e 's/^org.gradle.jvmargs=.*/org.gradle.jvmargs=-Xmx4096m -XX:MaxMetaspaceSize=1024m -XX:+UseParallelGC/' \
        -e '/^org.gradle.parallel/d' \
        gradle.properties
    grep -q '^org.gradle.parallel=false' gradle.properties || echo 'org.gradle.parallel=false' >> gradle.properties
fi

./gradlew assembleRelease --no-daemon --max-workers=2

# Copy APK to standard location for root wrapper
cp app/build/outputs/apk/release/app-release-unsigned.apk "$SCRIPT_DIR/unsigned.apk"
