#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="${SCRIPT_DIR}/setup_app_source.log"

# Logging function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Error handling
error_exit() {
    log "ERROR: $1"
    exit 1
}

# Check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Check Java installation
check_java() {
    log "Checking Java installation..."

    if ! command_exists java; then
        error_exit "Java is not installed. Please install OpenJDK 17 or newer"
    fi

    # Get Java version
    local java_version=$(java -version 2>&1 | head -n1 | cut -d'"' -f2 | cut -d'.' -f1)

    # Handle Java version format (8, 11, 17, etc.)
    if [[ "$java_version" =~ ^1\. ]]; then
        java_version=$(echo "$java_version" | cut -d'.' -f2)
    fi

    log "Detected Java version: $java_version"

    if [[ $java_version -lt 17 ]]; then
        error_exit "Java $java_version is too old. Android SDK requires Java 17 or newer"
    fi

    log "Java $java_version is compatible"
}

# Check and install build dependencies
install_build_dependencies() {
    log "Checking build dependencies..."

    # Check for required tools
    local missing_tools=()

    if ! command_exists git; then
        missing_tools+=("git")
    fi

    if ! command_exists make; then
        missing_tools+=("build-essential")
    fi

    if ! command_exists pkg-config; then
        missing_tools+=("pkg-config")
    fi

    # Check for Haskell Stack (required for SimpleX server components)
    if ! command_exists stack; then
        log "Installing Haskell Stack..."
        curl -sSL https://get.haskellstack.org/ | sh
        export PATH="$HOME/.local/bin:$PATH"
    fi

    # Check for Rust (required for some crypto components)
    if ! command_exists rustc; then
        log "Installing Rust..."
        curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
        source "$HOME/.cargo/env"
    fi

    if [[ ${#missing_tools[@]} -gt 0 ]]; then
        log "Missing tools: ${missing_tools[*]}"
        log "Please install them manually or run with sudo to auto-install"

        # Try to install on Ubuntu/Debian
        if command_exists apt-get; then
            log "Attempting to install missing dependencies..."
            sudo apt-get update
            for tool in "${missing_tools[@]}"; do
                sudo apt-get install -y "$tool"
            done
        else
            error_exit "Please install missing tools manually: ${missing_tools[*]}"
        fi
    fi
}

# Build SimpleX Chat from source
build_simplex_chat() {
    log "Building SimpleX Chat from source..."

    local source_dir="${SCRIPT_DIR}/simplex-chat"
    local app_dir="${SCRIPT_DIR}/apps/simplex-chat"
    local apk_dir="$app_dir/apk"

    # Create directories
    mkdir -p "$apk_dir"

    # Check if source exists
    if [[ ! -d "$source_dir" ]]; then
        error_exit "SimpleX Chat source not found at $source_dir"
    fi

    cd "$source_dir"

    # Get commit version for metadata
    local commit_version=$(git rev-parse --short HEAD)
    log "Building from commit: $commit_version"

    # Build native dependencies first
    log "Building native Haskell components..."
    cd "${source_dir}"

    # Build the simplexmq library that the Android app depends on
    if [[ -f "Makefile" ]]; then
        make android-deps || log "Warning: Android dependencies build failed or not required"
    fi

    # Build Android app
    log "Building Android APK..."
    cd "${source_dir}/apps/multiplatform"

    # Set up Android environment
    export ANDROID_HOME="${SCRIPT_DIR}/.android-sdk"
    export PATH="$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$ANDROID_HOME/build-tools/34.0.0:$PATH"

	log "Got to this point"
    # Clean previous builds
    ./gradlew clean --stacktrace -Dorg.gradle.jvmargs="--enable-native-access=ALL-UNNAMED" || error_exit "Gradle clean failed"

    # Build release APK
    log "Building release APK (this may take 10-20 minutes)..."
    ./gradlew :android:assembleRelease -Dorg.gradle.jvmargs="--enable-native-access=ALL-UNNAMED" || error_exit "APK build failed"

    # Find the built APK
    local built_apk=$(find . -name "*release*.apk" -type f | head -n1)

    if [[ -z "$built_apk" || ! -f "$built_apk" ]]; then
        error_exit "Built APK not found"
    fi

    log "Found built APK: $built_apk"

    # Copy APK to expected location
    local target_apk="${SCRIPT_DIR}/${apk_dir}/simplex-chat.apk"
    cp "$built_apk" "$target_apk"

    log "APK copied to: $target_apk"

    # Verify APK
    if [[ -f "$target_apk" ]]; then
        local apk_size=$(du -h "$target_apk" | cut -f1)
        log "SimpleX Chat APK built successfully (size: $apk_size)"

        # Show APK info
        if command_exists aapt; then
            log "APK information:"
            aapt dump badging "$target_apk" | head -n5 || true
        fi

        return 0
    else
        error_exit "Failed to copy APK to target location"
    fi
}

# Create signing key if needed
create_signing_key() {
    local keystore_path="${SCRIPT_DIR}/simplex-chat/debug.keystore"

    if [[ ! -f "$keystore_path" ]]; then
        log "Creating debug signing key..."
        keytool -genkey -v -keystore "$keystore_path" -alias androiddebugkey \
            -keyalg RSA -keysize 2048 -validity 10000 \
            -dname "CN=Debug,OU=Debug,O=Debug,L=Debug,S=Debug,C=US" \
            -storepass android -keypass android
    fi
}

# Main function
main() {
    log "Starting SimpleX Chat build from source"

    # Check prerequisites
    check_java
    install_build_dependencies

    # Create signing key
    create_signing_key

    # Build the app
    build_simplex_chat

    log "SimpleX Chat build completed successfully!"
    echo ""
    echo "APK Location: apps/simplex-chat/apk/simplex-chat.apk"
    echo ""
    echo "Next steps:"
    echo "1. Run ./setup.sh to set up the emulator and install the APK"
    echo "2. Or manually install with: adb install apps/simplex-chat/apk/simplex-chat.apk"
}

# Run main function
main "$@"
