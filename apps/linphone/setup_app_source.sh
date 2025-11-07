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
            -e 's/^org.gradle.jvmargs=.*/org.gradle.jvmargs=-Xmx4g -XX:MaxMetaspaceSize=1g -XX:+UseParallelGC -Dfile.encoding=UTF-8/' \
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
    
    # Set Java 17
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
    
    # Set Android SDK
    export ANDROID_HOME="$ANDROID_HOME"
    export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
    
    # Create local.properties for LinPhone build
    echo "sdk.dir=$ANDROID_HOME" > local.properties
    
    echo "Environment configured."
}

# Build LinPhone APK
build_LinPhone() {    
    echo "Building LinPhone Android from source..."
    echo "This will take several minutes..."

    local temp_out=$(mktemp)
    local temp_err=$(mktemp)
    if [ -f "./gradlew" ]; then
        echo "Gradle file exists"
    else
        echo "Gradle file missing"
    fi
    # Run gradle build with output suppressed
    pwd
    sed -i -- 's/signingConfigs.getByName("release")/signingConfigs.getByName("debug")/' app/build.gradle.kts
    if ./gradlew assembleRelease --no-daemon --max-workers=1 > "$temp_out" 2> "$temp_err"; then
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
    
    rm -rf app/build/intermediates 2>/dev/null || true
    rm -rf app/build/tmp 2>/dev/null || true
    rm -rf .gradle/buildOutputCleanup/cache.properties 2>/dev/null || true
    rm -rf node_modules/.cache 2>/dev/null || true
    
    if command -v yarn >/dev/null 2>&1; then
        yarn cache clean || true
    fi
    ./gradlew --stop
    
    echo "Clearing completed."
}


# Main function
main() {
    echo "LinPhone Android Setup"
    echo "==================="
    echo "Setting up LinPhone Android"

    cd codebase
    root_dir="$(pwd)"

    patch
    check_prerequisites
    setup_environment
    build_LinPhone
    clear
    
    echo ""
    echo "Setup complete! LinPhone is ready for testing."
}

# Run main function
main "$@"