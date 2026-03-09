#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
CODEBASE_DIR="$SCRIPT_DIR/codebase"
ANDROID_DIR="$CODEBASE_DIR/android"
ANDROID_HOME="${HOME}/.android-sdk"
source "$ROOT_DIR/utils/android.sh"

# Patch gradle.properties
patch() {
    cd $ANDROID_DIR
    # Patch gradle.properties for low-RAM builds
    echo "Patching gradle.properties for low memory usage..."
        
    # Remove MaxPermSize if present (deprecated in newer Java versions)
    sed -i.bak 's/-XX:MaxPermSize=[^ ]*//g' gradle.properties
    
    # More aggressive memory settings for Jitsi
    sed -i.bak \
        -e 's/^org.gradle.jvmargs=.*/org.gradle.jvmargs=-Xmx6144m -XX:MaxMetaspaceSize=1024m -XX:+UseParallelGC -Dfile.encoding=UTF-8 -Xss8m/' \
        -e '/^org.gradle.parallel/d' \
        -e '/^android.enableR8/d' \
        -e '/^org.gradle.daemon/d' \
        gradle.properties
    
    # Append if missing
    grep -q '^org.gradle.parallel=false' gradle.properties || echo 'org.gradle.parallel=false' >> gradle.properties
    grep -q '^org.gradle.daemon=false' gradle.properties || echo 'org.gradle.daemon=false' >> gradle.properties
    
    # Increase Node memory for React Native bundling
    grep -q '^NODE_OPTIONS=' gradle.properties || echo 'NODE_OPTIONS=--max-old-space-size=4096' >> gradle.properties
}

# Clean function - run BEFORE build
clean_build() {

    echo "Cleaning build caches..."
    cd $CODEBASE_DIR

    # Fallback for systems where TMPDIR is not set (e.g. Linux)
    TMPDIR="${TMPDIR:-/tmp}"

    # Clean Metro bundler cache
    rm -rf node_modules/.cache 2>/dev/null || true
    rm -rf .metro 2>/dev/null || true
    rm -rf $TMPDIR/metro-* 2>/dev/null || true
    rm -rf $TMPDIR/react-* 2>/dev/null || true
    
    cd $ANDROID_DIR
    # Clean gradle caches
    ./gradlew clean || true
    rm -rf .gradle 2>/dev/null || true
    rm -rf build 2>/dev/null || true
    rm -rf app/build 2>/dev/null || true
    
    # Stop any running gradle daemons
    ./gradlew --stop
    
    echo "Clean completed."
}

# Check prerequisites
check_prerequisites() {
    echo "Checking prerequisites..."
    
    cd $CODEBASE_DIR
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
    
    # Create local.properties for joplin build
    echo "sdk.dir=$ANDROID_HOME" > local.properties
    
    echo "Environment configured."
}

# Build Jitsi Meet APK
build_jitsi() {    
    echo "=================================================="
    echo "Building Jitsi Meet Android from source..."
    echo "This will take several minutes..."
    echo "=================================================="
    
    cd $CODEBASE_DIR

    # Fallback for systems where TMPDIR is not set (e.g. Linux)
    TMPDIR="${TMPDIR:-/tmp}"
    
    echo ">>> Clearing Metro bundler cache..."
    rm -rf $TMPDIR/metro-* 2>/dev/null || true
    rm -rf $TMPDIR/haste-map-* 2>/dev/null || true
    rm -rf node_modules/.cache 2>/dev/null || true
    
    echo ">>> Proceeding with Gradle build..."
    cd $ANDROID_DIR

    echo ">>> Cleaning Gradle Build Caches..."
    ./gradlew clean

    echo ">>> Starting Gradle Build..."
    ./gradlew assembleRelease \
        --no-daemon \
        --max-workers=2 \
        --console=plain \
        -Dorg.gradle.jvmargs="-Xmx6144m -Xss8m"
}
copy_apk() {
    echo "Locating unsigned APK..."
    cd $ANDROID_DIR

    local output_dir="app/build/outputs/apk"
    local apk_dest="$SCRIPT_DIR"
    local apk_new_name="unsigned.apk"
    
    ls

    if [[ ! -d "$output_dir" ]]; then
        echo "ERROR: APK output directory not found: $output_dir"
        exit 1
    fi

    # Prefer release APKs, fall back to anything unsigned
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

clear() {
    echo "Clearing cache - preserving working build state..."
    cd $ANDROID_DIR
    
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
    echo ">>> Jitsi Meet Android Setup"
    echo "========================"
    echo ">>> Setting up Jitsi Meet Android"

    cd $CODEBASE_DIR
    echo ">>> Cleaning up old React Native CLI packages..."
    npm uninstall -g react-native-cli @react-native-community/cli
    echo ">>> Installing yarn and project dependencies..."
    npm install -g yarn && yarn install
    echo ">>> Finished installing packages."

    echo ">>> Configuring environment..."
    patch
    check_prerequisites

    echo ">>> Starting build process..."
    build_jitsi
    copy_apk
    clear

    echo ""
    echo ">>> Setup complete! Jitsi Meet is ready for testing."
}

main "$@"