#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

npm install
npm install es6-promise-plugin
npm run generate
npx cap sync android

# Capacitor 7.x and its plugins hardcode Java 21 in their build.gradle files.
# Patch all of them to Java 17 since that's what this project requires.
find node_modules -name "build.gradle" -path "*/android/*" -exec \
    sed -i.bak 's/JavaVersion.VERSION_21/JavaVersion.VERSION_17/g' {} +

cd android

# Patch gradle.properties for low-RAM builds
if [[ -f "gradle.properties" ]]; then
    echo "Patching gradle.properties for low memory usage..."
    sed -i.bak \
        -e 's/^org.gradle.jvmargs=.*/org.gradle.jvmargs=-Xmx1024m -XX:MaxMetaspaceSize=512m -XX:+UseParallelGC -Dfile.encoding=UTF-8/' \
        -e '/^org.gradle.parallel/d' \
        -e '/^android.enableR8/d' \
        gradle.properties
    grep -q '^org.gradle.parallel=false' gradle.properties || echo 'org.gradle.parallel=false' >> gradle.properties
fi

# Use debug signing config for release build
sed -i -- 's/signingConfig signingConfigs.release/signingConfig signingConfigs.debug/' app/build.gradle

./gradlew assembleRelease --no-daemon --max-workers=1

# Copy unsigned APK to standard location for root wrapper
APK=$(find app/build/outputs/apk/release/ -name '*-release-unsigned.apk' -type f | head -1)
if [[ -z "$APK" ]]; then
    echo "ERROR: No unsigned APK found after build" >&2
    exit 1
fi
cp "$APK" "$SCRIPT_DIR/unsigned.apk"
