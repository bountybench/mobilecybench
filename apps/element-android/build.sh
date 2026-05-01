#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
CODEBASE_DIR="$SCRIPT_DIR/codebase"
ANDROID_HOME="${HOME}/.android-sdk"
source "$ROOT_DIR/utils/android.sh"

if [[ ! -d "$ANDROID_HOME" && -d "/usr/local/lib/android/sdk" ]]; then
    ANDROID_HOME="/usr/local/lib/android/sdk"
fi

#4 Workers + 7g heap built in 10m locally
CI_WORKERS=4
JVM_HEAP="-Xmx7g -XX:MaxMetaspaceSize=512m -XX:+UseParallelGC -Xss4m -Dfile.encoding=UTF-8"

setup_environment() {
    if [[ -d "/opt/homebrew/opt/openjdk@17" ]]; then
        export JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home
    elif [[ -d "/usr/lib/jvm/java-17-openjdk" ]]; then
        export JAVA_HOME=/usr/lib/jvm/java-17-openjdk
    elif command -v /usr/libexec/java_home &>/dev/null; then
        export JAVA_HOME="$(/usr/libexec/java_home -v 17)"
    else
        export JAVA_HOME=$(java -XshowSettings:properties -version 2>&1 | grep 'java.home' | awk '{print $3}')
    fi

    export PATH="$JAVA_HOME/bin:$PATH"
    export ANDROID_HOME
    export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"

    echo "sdk.dir=$ANDROID_HOME" > "$CODEBASE_DIR/local.properties"
    echo "Environment configured (JAVA_HOME=$JAVA_HOME)"
}

patch_gradle_properties() {
    cd "$CODEBASE_DIR"

    sed -i.bak \
        -e 's/-XX:MaxPermSize=[^ ]*//g' \
        -e '/^org\.gradle\.jvmargs/d'   \
        -e '/^org\.gradle\.parallel/d'  \
        -e '/^org\.gradle\.daemon/d'    \
        -e '/^org\.gradle\.caching/d'   \
        -e '/^org\.gradle\.vfs\.watch/d'\
        -e '/^kotlin\.daemon\.jvmargs/d'\
        gradle.properties

    cat >> gradle.properties <<EOF
org.gradle.jvmargs=$JVM_HEAP
org.gradle.parallel=true
org.gradle.daemon=false
org.gradle.caching=false
android.lint.checkReleaseBuilds=false
EOF
}

restore_gradle_properties() {
    cd "$CODEBASE_DIR"
    if [[ -f gradle.properties.bak ]]; then
        mv gradle.properties.bak gradle.properties
        echo "gradle.properties restored"
    fi
}

check_prerequisites() {
    command -v java >/dev/null 2>&1 || { echo "ERROR: Java not found."; exit 1; }
    [[ -d "$ANDROID_HOME" ]]        || { echo "ERROR: Android SDK not found at $ANDROID_HOME"; exit 1; }
    java -version
    echo "Prerequisites OK"
}

build_element() {
    cd "$CODEBASE_DIR"
    echo "=================================================="
    echo "Building Element Android — cold CI, $CI_WORKERS workers"
    echo "=================================================="

    ./gradlew assembleFdroidRustCryptoRelease --no-daemon -PallWarningsAsErrors=false ${GRADLE_EXTRA_ARGS:-}
}

copy_apk() {
    cd "$CODEBASE_DIR"
    local output_dir="vector-app/build/outputs/apk"

    [[ -d "$output_dir" ]] || { echo "ERROR: APK output dir not found: $output_dir"; exit 1; }

    local apk_source
    apk_source="$(find "$output_dir" -type f -name "vector-fdroid-rustCrypto-universal-release*.apk" | head -n 1)"

    [[ -n "$apk_source" ]] || {
        echo "ERROR: No APK found. Available files:"
        find "$output_dir" -name "*.apk" -type f
        exit 1
    }

    cp "$apk_source" "$SCRIPT_DIR/unsigned.apk"
    echo "APK → $SCRIPT_DIR/unsigned.apk (source: $apk_source)"
}

clear_intermediate_cache() {
    cd "$CODEBASE_DIR"
    rm -rf vector-app/build/intermediates vector-app/build/tmp 2>/dev/null || true
}

main() {
    echo ">>> Element Android CI Build"
    cd "$CODEBASE_DIR"
    setup_environment
    patch_gradle_properties
    check_prerequisites
    build_element
    copy_apk
    clear_intermediate_cache
    restore_gradle_properties
    echo ">>> Done. APK at $SCRIPT_DIR/unsigned.apk"
}

main "$@"