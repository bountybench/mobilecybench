#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
ANDROID_HOME="${HOME}/.android-sdk"
source "$ROOT_DIR/utils/android.sh"

# Patch gradle.properties
patch() {
    # Patch gradle.properties for low-RAM builds
    if [[ -f "gradle.properties" ]]; then
        echo "Patching gradle.properties for low memory usage..."
        sed -i.bak \
            -e 's/^org.gradle.jvmargs=.*/org.gradle.jvmargs=-Xmx1024m -XX:MaxMetaspaceSize=512m -XX:+UseParallelGC -Dfile.encoding=UTF-8/' \
            -e '/^org.gradle.parallel/d' \
            -e '/^android.enableR8/d' \
            gradle.properties
        # Append if missing
        grep -q '^org.gradle.parallel=false' gradle.properties || echo 'org.gradle.parallel=false' >> gradle.properties
    fi
}

# Check prerequisites
check_prerequisites() {
    echo "Checking prerequisites..."

    # Check Java 17
    if ! command -v java >/dev/null 2>&1; then
        echo "ERROR: Java not found. Please install Java 17."
        exit 1
    fi

    if [[ ! -d "$ANDROID_HOME" && -d "/usr/local/lib/android/sdk" ]]; then
        ANDROID_HOME="/usr/local/lib/android/sdk"
    fi

    # Check Android SDK
    if [[ ! -d "$ANDROID_HOME" ]]; then
        echo "ERROR: Android SDK not found at $ANDROID_HOME"
        echo "Please run the Android emulator setup first."
        exit 1
    fi

    echo "Prerequisites verified."
}

# Setup environment
setup_environment() {
    echo "Setting up build environment..."

    # Set Java 17 or higher (WordPress requires Java 17+)
    if command -v /usr/libexec/java_home &>/dev/null; then
        # Try to get Java 21 first, then 17
        if /usr/libexec/java_home -v 21 >/dev/null 2>&1; then
            export JAVA_HOME="$(/usr/libexec/java_home -v 21)"
        elif /usr/libexec/java_home -v 17 >/dev/null 2>&1; then
            export JAVA_HOME="$(/usr/libexec/java_home -v 17)"
        else
            # Default to latest version
            export JAVA_HOME="$(/usr/libexec/java_home)"
        fi
    elif [[ -d "/opt/homebrew/opt/openjdk@21" ]]; then
        export JAVA_HOME=/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home
    elif [[ -d "/opt/homebrew/opt/openjdk@17" ]]; then
        export JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home
    elif [[ -d "/usr/lib/jvm/java-21-openjdk" ]]; then
        export JAVA_HOME=/usr/lib/jvm/java-21-openjdk
    elif [[ -d "/usr/lib/jvm/java-17-openjdk" ]]; then
        export JAVA_HOME=/usr/lib/jvm/java-17-openjdk
    else
        export JAVA_HOME=$(java -XshowSettings:properties -version 2>&1 | grep 'java.home' | awk '{print $3}')
    fi
    echo "Using Java: $JAVA_HOME"
    export PATH="$JAVA_HOME/bin:$PATH"

    # Verify Java version
    java -version

    # Set Android SDK
    export ANDROID_HOME="$ANDROID_HOME"
    export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"

    # Create local.properties for WordPress build
    echo "sdk.dir=$ANDROID_HOME" > local.properties

    echo "Environment configured."
}

# Build WordPress APK
build_wordpress() {
    echo "Building WordPress Android from source..."
    echo "This will take several minutes..."

    local temp_out=$(mktemp)
    local temp_err=$(mktemp)

    # Run gradle build with output suppressed (use WordPress variant)
    if ./gradlew assembleWordpressVanillaDebug --no-daemon --max-workers=1 > "$temp_out" 2> "$temp_err"; then
        echo "Build completed successfully."
        # Clean up temp files on success
        rm -f "$temp_out" "$temp_err"
    else
        local exit_code=$?
        echo "ERROR: Build failed with exit code $exit_code"

        # Show stderr (which contains the actual error messages)
        if [[ -s "$temp_err" ]]; then
            echo "Error output:"
            cat "$temp_err"
        fi

        # Optionally show last part of stdout for context
        if [[ -s "$temp_out" ]]; then
            echo "Last 50 lines of build output:"
            tail -50 "$temp_out"
        fi

        # Clean up temp files
        rm -f "$temp_out" "$temp_err"
        exit $exit_code
    fi
}

clear() {
    echo "Clearing cache - preserving working build state..."

    rm -rf WordPress/build/intermediates 2>/dev/null || true
    rm -rf WordPress/build/tmp 2>/dev/null || true
    rm -rf .gradle/buildOutputCleanup/cache.properties 2>/dev/null || true

    ./gradlew --stop

    echo "Clearing completed."
}

# Clean build directories completely
clean_build() {
    echo "Cleaning build directories completely..."

    ./gradlew clean --no-daemon || true
    rm -rf WordPress/build 2>/dev/null || true
    rm -rf .gradle 2>/dev/null || true
    rm -rf build 2>/dev/null || true

    echo "Clean completed."
}

# Main function
main() {
    echo "WordPress Android Setup"
    echo "======================"
    echo "Setting up WordPress Android"

    root_dir="$(pwd)"
    if [[ -d "codebase" ]]; then
        echo "Navigating to codebase directory..."
        cd codebase
    else
        echo "ERROR: Not in WordPress Android directory and codebase/ not found."
        exit 1
    fi

    patch
    check_prerequisites
    setup_environment
    clean_build
    build_wordpress
    clear

    echo ""
    echo "Setup complete! WordPress is ready for testing."
}

# Run main function
main "$@"