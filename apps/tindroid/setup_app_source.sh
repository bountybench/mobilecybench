
#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

LOG_PREFIX="[setup_app_source]"
LOG_FILE="${SCRIPT_DIR}/setup_app_source.log"
# Duplicate outputs to console and log file
exec > >(tee -a "$LOG_FILE") 2>&1
info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*"; }
error(){ printf '%s[error] %s\n' "$LOG_PREFIX" "$*"; exit 1; }

# Set Android SDK path - handle both local development and CI environments
if [[ -n "$ANDROID_HOME" && -d "$ANDROID_HOME" ]]; then
    # Use existing ANDROID_HOME if set and valid
    info "Using existing ANDROID_HOME: $ANDROID_HOME"
elif [[ -d "/usr/local/lib/android/sdk" ]]; then
    # GitHub Actions default path
    ANDROID_HOME="/usr/local/lib/android/sdk"
    info "Using GitHub Actions Android SDK path: $ANDROID_HOME"
elif [[ -d "${HOME}/.android-sdk" ]]; then
    # Local development default path
    ANDROID_HOME="${HOME}/.android-sdk"
    info "Using local development Android SDK path: $ANDROID_HOME"
else
    error "Android SDK not found in any expected location"
fi

# Check prerequisites
check_prerequisites() {
    info "Checking prerequisites (Java and Android SDK)..."
    
    # Check Java
    if ! command -v java >/dev/null 2>&1; then
        error "Java not found. Please install Java 17."
    fi
    
    # Check Android SDK
    if [[ ! -d "$ANDROID_HOME" ]]; then
        error "Android SDK not found at $ANDROID_HOME. Please run the Android emulator setup first."
    fi
    
    info "Prerequisites verified."
}

setup_environment() {
    info "Setting up build environment..."
    
    # Set Java 17 - use existing JAVA_HOME if available, otherwise fallback to macOS path
    if [[ -n "$JAVA_HOME" && -d "$JAVA_HOME" ]]; then
        info "Using existing JAVA_HOME: $JAVA_HOME"
    elif [[ -d "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home" ]]; then
        # macOS Homebrew path
        export JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home
        info "Using macOS Homebrew JAVA_HOME: $JAVA_HOME"
    elif [[ -d "/usr/lib/jvm/java-17-openjdk" ]]; then
        # Linux path
        export JAVA_HOME=/usr/lib/jvm/java-17-openjdk
        info "Using Linux JAVA_HOME: $JAVA_HOME"
    else
        warn "Could not find Java 17 via known paths. Using system default."
        export JAVA_HOME=$(java -XshowSettings:properties -version 2>&1 | grep 'java.home' | awk '{print $3}')
    fi
    
    export PATH="$JAVA_HOME/bin:$PATH"
    
    # Set Android SDK
    export ANDROID_HOME="$ANDROID_HOME"
    export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
    
    # Create local.properties for Tindroid build
    echo "sdk.dir=$ANDROID_HOME" > local.properties

    # Create keystore.properties for Tindroid build
    if [ ! -f keystore.properties ]; then
        echo "storeFile=debug.keystore
storePassword=android
keyAlias=androiddebugkey
keyPassword=android" >> keystore.properties
    else
        echo "storeFile=debug.keystore
storePassword=android
keyAlias=androiddebugkey
keyPassword=android" > keystore.properties
    fi

    # There should be a dummy google-services.json file in the Tindroid root directory.
    # The Tindroid app requires Firebase services for all build variants.
    # Copy google-services.json from the Tindroid root directory to app/google-services.json inside the codebase directory.
    if [ ! -f ../google-services.json ]; then
        error "google-services.json not found in the Tindroid root directory. Please copy a valid google-services.json file to the Tindroid root directory."
    else
        cp "../google-services.json" "app/google-services.json"
    fi
    
    info "Environment configured."
}

# Build Tindroid APK
build_tindroid() {
    # Check if APK already exists
    APK_PATH="app/build/outputs/apk/debug/app-debug.apk"
    if [[ -f "$APK_PATH" ]]; then
        info "APK already exists at $APK_PATH - skipping build"
        return 0
    fi
    
    info "Building Tindroid Android from source (this may take several minutes)..."
    
    # Build with Gradle and override JVM args to fix Java 8+ compatibility
    ./gradlew assembleDebug -Dorg.gradle.jvmargs="-Xmx4096m -XX:+HeapDumpOnOutOfMemoryError -Dfile.encoding=UTF-8"
    
    info "Build completed successfully."
}

main() {
    info "Tindroid Android Setup"
    echo "====================="
    
    CODEBASE_DIR="$SCRIPT_DIR/codebase"
    if [[ ! -d "$CODEBASE_DIR" ]]; then
        error "Tindroid codebase directory not found at $CODEBASE_DIR"
    fi
    
    cd "$CODEBASE_DIR"
    
    if [[ ! -f "gradlew" ]]; then
        error "gradlew not found in codebase directory."
    fi
    
    check_prerequisites
    setup_environment
    build_tindroid
    
    echo ""
    echo "=========================================="
    info "Tindroid Build complete! Tindroid is ready to be installed"
    echo "=========================================="
    echo ""
}

# Run main function
main "$@"
