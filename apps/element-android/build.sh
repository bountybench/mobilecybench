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

# GitHub Actions standard runners: 4 vCPU, 16GB RAM shared with OS + tooling.
# 3 workers: leaves 1 core for the OS/linker, avoids thrashing.
# 6g heap: safe ceiling — OS + SDK tools + in-process Kotlin compiler all share the 16GB.
CI_WORKERS=3
JVM_HEAP="-Xmx6g -XX:MaxMetaspaceSize=512m -XX:+UseParallelGC -Xss4m -Dfile.encoding=UTF-8"

setup_environment() {
    if   [[ -d "/opt/homebrew/opt/openjdk@17" ]]; then
        export JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home
    elif [[ -d "/usr/lib/jvm/java-17-openjdk-amd64" ]]; then
        export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
    elif [[ -d "/usr/lib/jvm/java-17-openjdk" ]]; then
        export JAVA_HOME=/usr/lib/jvm/java-17-openjdk
    elif command -v /usr/libexec/java_home &>/dev/null; then
        export JAVA_HOME="$(/usr/libexec/java_home -v 17 2>/dev/null)"
    elif [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" || -n "$WINDIR" ]]; then
        # On Windows, use JAVA_HOME if already set in the environment (most reliable),
        # otherwise query the registry via where.exe to find the real path.
        # Do NOT use the awk fallback — it splits on spaces in "C:\Program Files\..."
        if [[ -n "${JAVA_HOME:-}" && -d "${JAVA_HOME}" ]]; then
            : # already valid, use it as-is
        else
            # Resolve via where.exe — gives us the java.exe path, strip to home dir
            local java_exe
            java_exe=$(where.exe java 2>/dev/null | head -1)
            if [[ -n "$java_exe" ]]; then
                # Convert to Unix path and strip \bin\java.exe
                JAVA_HOME=$(cd "$(dirname "$java_exe")/.." && pwd)
            else
                echo "ERROR: Could not detect JAVA_HOME on Windows. Set it manually."
                exit 1
            fi
        fi
        export JAVA_HOME
    else
        # Last resort — awk fallback, safe on Linux/Mac where paths have no spaces
        export JAVA_HOME="$(java -XshowSettings:properties -version 2>&1 \
                            | awk '/java.home/{print $3}')"
    fi

    export PATH="$JAVA_HOME/bin:$PATH"
    export ANDROID_HOME
    export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"

    echo "sdk.dir=$ANDROID_HOME" > "$CODEBASE_DIR/local.properties"
    echo "Environment configured (JAVA_HOME=$JAVA_HOME)"
}

patch_gradle_properties() {
    cd "$CODEBASE_DIR"

    # Strip every line we own before appending — prevents duplicates if
    # this script runs more than once, and eliminates conflicting jvmargs
    # that would cause the Gradle daemon to restart mid-build.
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

    ./gradlew assembleFdroidKotlinCryptoRelease \
        --no-daemon                                             \
        --no-build-cache                                        \
        --max-workers="$CI_WORKERS"                             \
        --console=plain                                         \
        -x lintVitalAnalyzeFdroidKotlinCryptoRelease            \
        -x lintVitalReportFdroidKotlinCryptoRelease             \
        -x lintVitalFdroidKotlinCryptoRelease                   \
        -Pandroid.lint.abortOnError=false                       \
        -Dkotlin.incremental=false                              \
        -Dkotlin.compiler.execution.strategy=in-process         \
        -Dkotlin.daemon.useFallbackStrategy=false
}

copy_apk() {
    cd "$CODEBASE_DIR"
    local output_dir="vector-app/build/outputs/apk"

    [[ -d "$output_dir" ]] || { echo "ERROR: APK output dir not found: $output_dir"; exit 1; }

    local apk_source
    apk_source="$(find "$output_dir" -type f \
        \( -name "*unsigned*.apk" -o \( -name "*.apk" ! -name "*signed*" \) \) \
        | head -n 1)"

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
    echo ">>> Done. APK at $SCRIPT_DIR/unsigned.apk"
}

main "$@"