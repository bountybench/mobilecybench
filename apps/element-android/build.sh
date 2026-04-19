#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
CODEBASE_DIR="$SCRIPT_DIR/codebase"
ANDROID_HOME="${HOME}/.android-sdk"
source "$ROOT_DIR/utils/android.sh"

# Patch gradle.properties
patch() {
    cd $CODEBASE_DIR

    echo "Patching gradle.properties for low memory usage..."

    # Remove MaxPermSize if present (deprecated in newer Java versions)
    sed -i.bak 's/-XX:MaxPermSize=[^ ]*//g' gradle.properties

    sed -i.bak \
        -e 's/^org.gradle.jvmargs=.*/org.gradle.jvmargs=-Xmx6144m -XX:MaxMetaspaceSize=1024m -XX:+UseParallelGC -Dfile.encoding=UTF-8 -Xss8m/' \
        -e '/^org.gradle.parallel/d' \
        -e '/^android.enableR8/d' \
        -e '/^org.gradle.daemon/d' \
        -e '/^kotlin.daemon.jvmargs/d' \
        gradle.properties

    grep -q '^org.gradle.parallel=false' gradle.properties || echo 'org.gradle.parallel=false' >> gradle.properties
    grep -q '^org.gradle.daemon=false' gradle.properties || echo 'org.gradle.daemon=false' >> gradle.properties
    grep -q '^kotlin.daemon.jvmargs' gradle.properties || echo 'kotlin.daemon.jvmargs=-Xmx2g' >> gradle.properties
}
# Clean function - run BEFORE build
clean_build() {
    echo "Cleaning build caches..."
    cd $CODEBASE_DIR

    ./gradlew clean || true
    rm -rf .gradle 2>/dev/null || true
    rm -rf build 2>/dev/null || true
    rm -rf vector-app/build 2>/dev/null || true

    echo "Clean completed."
}

# Check prerequisites
check_prerequisites() {
    echo "Checking prerequisites..."

    cd $CODEBASE_DIR

    if ! command -v java >/dev/null 2>&1; then
        echo "ERROR: Java not found. Please install Java 17."
        exit 1
    fi

    if [[ ! -d "$ANDROID_HOME" && -d "/usr/local/lib/android/sdk" ]]; then
        ANDROID_HOME="/usr/local/lib/android/sdk"
    fi

    if [[ ! -d "$ANDROID_HOME" ]]; then
        echo "ERROR: Android SDK not found at $ANDROID_HOME"
        echo "Please run the Android emulator setup first."
        exit 1
    fi

    echo "Prerequisites verified."
}

setup_environment() {
    echo "Setting up build environment..."
    
    if [[ -d "/opt/homebrew/opt/openjdk@17" ]]; then
        export JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home
    elif [[ -d "/usr/lib/jvm/java-17-openjdk" ]]; then
        export JAVA_HOME=/usr/lib/jvm/java-17-openjdk
    elif command -v /usr/libexec/java_home &>/dev/null; then
        export JAVA_HOME="$(/usr/libexec/java_home -v 17)"
    else
        export JAVA_HOME=$(java -XshowSettings:properties -version 2>&1 | grep 'java.home' | awk '{print $3}')
    fi
    echo $JAVA_HOME
    export PATH="$JAVA_HOME/bin:$PATH"

    export ANDROID_HOME="$ANDROID_HOME"
    export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"

    # Create local.properties
    echo "sdk.dir=$ANDROID_HOME" > local.properties

    echo "Environment configured."
}

# Build Element Android APK
build_element() {
    echo "=================================================="
    echo "Building Element Android from source..."
    echo "This will take several minutes..."
    echo "=================================================="

    cd $CODEBASE_DIR

    echo ">>> Cleaning Gradle Build Caches..."
    ./gradlew clean

    export GRADLE_OPTS="-Xmx4g -Dkotlin.daemon.jvm.options=-Xmx1g -XX:MaxMetaspaceSize=512m"

    ./gradlew assembleFdroidKotlinCryptoRelease \
        --no-daemon \
        --max-workers=2 \
        --console=plain \
        -x lint \
        -x lintFdroidKotlinCryptoRelease \
        -x lintAnalyzeFdroidKotlinCryptoRelease \
        -x lintVitalAnalyzeFdroidKotlinCryptoRelease \
        -x test \
        -Dorg.gradle.parallel=false \
        -Dorg.gradle.jvmargs="-Xmx4g -Xss4m -XX:MaxMetaspaceSize=512m" \
        -Dkotlin.daemon.jvm.options="-Xmx1g" \
        -Pandroid.lint.abortOnError=false \
        -Pandroid.lint.checkReleaseBuilds=false
}

copy_apk() {
    echo "Locating unsigned APK..."
    cd $CODEBASE_DIR

    local output_dir="vector-app/build/outputs/apk"
    local apk_dest="$SCRIPT_DIR"
    local apk_new_name="unsigned.apk"

    ls

    if [[ ! -d "$output_dir" ]]; then
        echo "ERROR: APK output directory not found: $output_dir"
        exit 1
    fi

    local apk_source
    apk_source="$(find "$output_dir" -type f \
        \( -name "*unsigned*.apk" -o \( -name "*.apk" ! -name "*signed*" \) \) \
        | head -n 1)"

    if [[ -z "$apk_source" ]]; then
        echo "ERROR: No APK found in $output_dir"
        echo "Available APKs:"
        find "$output_dir" -name "*.apk" -type f
        exit 1
    fi

    mkdir -p "$apk_dest"
    cp "$apk_source" "$apk_dest/$apk_new_name"

    echo "APK copied:"
    echo "  Source: $apk_source"
    echo "  Dest:   $apk_dest/$apk_new_name"
}

clear_cache() {
    echo "Clearing cache - preserving working build state..."
    cd $CODEBASE_DIR

    rm -rf vector-app/build/intermediates 2>/dev/null || true
    rm -rf vector-app/build/tmp 2>/dev/null || true
    rm -rf .gradle/buildOutputCleanup/cache.properties 2>/dev/null || true

    echo "Clearing completed."
}

# Main function
main() {
    echo ">>> Element Android Setup"
    echo "========================"

    cd $CODEBASE_DIR

    echo ">>> Configuring environment..."
    setup_environment
    patch
    check_prerequisites

    echo ">>> Starting build process..."
    build_element
    copy_apk
    clear_cache

    echo ""
    echo ">>> Setup complete! Element Android is ready for testing."
}

main "$@"