#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

npm install
npm run generate
npx cap sync android

# Capacitor 7.x and its plugins hardcode Java 21 in their build.gradle files.
# Patch all of them to Java 17 since that's what this project requires.
find node_modules -name "build.gradle" -path "*/android/*" -exec \
    sed -i.bak 's/JavaVersion.VERSION_21/JavaVersion.VERSION_17/g' {} +

cd android

GRADLE_ARGS=()
if [ "${MCB_OBFUSCATE:-0}" = "1" ] && [ -n "${MCB_OBFUSCATE_INIT_SCRIPT:-}" ]; then
    GRADLE_ARGS+=(--init-script "$MCB_OBFUSCATE_INIT_SCRIPT")
fi

# Patch gradle.properties. Default builds keep the low-RAM profile; obfuscated
# builds need more heap because R8 minifies the full release app and otherwise
# fails with GC-overhead OOM in CI.
if [[ -f "gradle.properties" ]]; then
    if [ "${MCB_OBFUSCATE:-0}" = "1" ]; then
        GRADLE_JVMARGS="-Xmx4096m -XX:MaxMetaspaceSize=1024m -XX:+UseParallelGC -Dfile.encoding=UTF-8"
        echo "Patching gradle.properties for obfuscated R8 build..."
    else
        GRADLE_JVMARGS="-Xmx1024m -XX:MaxMetaspaceSize=512m -XX:+UseParallelGC -Dfile.encoding=UTF-8"
        echo "Patching gradle.properties for low memory usage..."
    fi
    sed -i.bak \
        -e "s/^org.gradle.jvmargs=.*/org.gradle.jvmargs=${GRADLE_JVMARGS}/" \
        -e '/^org.gradle.parallel/d' \
        -e '/^android.enableR8/d' \
        gradle.properties
    grep -q '^org.gradle.parallel=false' gradle.properties || echo 'org.gradle.parallel=false' >> gradle.properties
fi

# Use debug signing config for release build
sed -i -- 's/signingConfig signingConfigs.release/signingConfig signingConfigs.debug/' app/build.gradle

./gradlew "${GRADLE_ARGS[@]}" assembleRelease --no-daemon --max-workers=1

# Copy unsigned APK to standard location for root wrapper
APK=$(find app/build/outputs/apk/release/ -name '*-release-unsigned.apk' -type f | head -1)
if [[ -z "$APK" ]]; then
    echo "ERROR: No unsigned APK found after build" >&2
    exit 1
fi
cp "$APK" "$SCRIPT_DIR/unsigned.apk"
