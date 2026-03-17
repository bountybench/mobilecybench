#!/bin/bash
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

./gradlew assembleFdroidRustCryptoRelease --no-daemon --max-workers=2 -PallWarningsAsErrors=false ${GRADLE_EXTRA_ARGS:-}

# Copy universal APK to standard location for root wrapper
cp vector-app/build/outputs/apk/fdroidRustCrypto/release/vector-fdroid-rustCrypto-universal-release*.apk "$SCRIPT_DIR/unsigned.apk"
