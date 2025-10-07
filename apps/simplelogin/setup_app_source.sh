#!/bin/bash

# SimpleLogin Android App Source Setup Script
# Part of MobileCybench - builds and installs SimpleLogin Android app

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODEBASE_DIR="$SCRIPT_DIR/codebase"
METADATA_FILE="$SCRIPT_DIR/metadata.json"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_prerequisites() {
    log_info "Checking prerequisites..."
    
    # Check if metadata exists
    if [[ ! -f "$METADATA_FILE" ]]; then
        log_error "metadata.json not found at $METADATA_FILE"
        return 1
    fi
    
    # Check Java
    if ! command -v java &> /dev/null; then
        log_error "Java not found. Please install Java 17 or later."
        return 1
    fi
    
    # Set Android SDK path - handle both local development and CI environments
    if [[ -n "$ANDROID_HOME" && -d "$ANDROID_HOME" ]]; then
        # Use existing ANDROID_HOME if set and valid
        log_info "Using existing ANDROID_HOME: $ANDROID_HOME"
    elif [[ -d "/usr/local/lib/android/sdk" ]]; then
        # GitHub Actions default path
        ANDROID_HOME="/usr/local/lib/android/sdk"
        log_info "Using GitHub Actions Android SDK path: $ANDROID_HOME"
    elif [[ -d "${HOME}/.android-sdk" ]]; then
        # Local development default path
        ANDROID_HOME="${HOME}/.android-sdk"
        log_info "Using local development Android SDK path: $ANDROID_HOME"
    else
        log_error "Android SDK not found in any expected location"
        return 1
    fi
    
    # Check Android SDK
    if [[ ! -d "$ANDROID_HOME" ]]; then
        log_error "Android SDK not found at $ANDROID_HOME. Please run the Android emulator setup first."
        return 1
    fi
    
    # Set up Android SDK environment
    export ANDROID_HOME="$ANDROID_HOME"
    export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
    
    # Check ADB
    if ! command -v adb &> /dev/null; then
        log_error "adb not found. Please install Android SDK platform-tools."
        return 1
    fi
    
    # Check Git
    if ! command -v git &> /dev/null; then
        log_error "git not found. Please install git."
        return 1
    fi
    
    log_success "Prerequisites check passed"
}



setup_environment() {
    log_info "Setting up build environment..."
    
    # Set Java 17 - use existing JAVA_HOME if available, otherwise detect
    if [[ -n "${JAVA_HOME:-}" && -d "${JAVA_HOME:-}" ]]; then
        log_info "Using existing JAVA_HOME: $JAVA_HOME"
    elif [[ -d "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home" ]]; then
        # macOS Homebrew path
        export JAVA_HOME="/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"
        log_info "Using macOS Homebrew JAVA_HOME: $JAVA_HOME"
    elif [[ -d "/usr/lib/jvm/java-17-openjdk" ]]; then
        # Linux path
        export JAVA_HOME="/usr/lib/jvm/java-17-openjdk"
        log_info "Using Linux JAVA_HOME: $JAVA_HOME"
    else
        log_warning "Could not find Java 17 via known paths. Using system default."
        export JAVA_HOME=$(java -XshowSettings:properties -version 2>&1 | grep 'java.home' | awk '{print $3}')
    fi
    
    export PATH="$JAVA_HOME/bin:$PATH"
    log_success "Build environment configured"
}

build_app() {
    log_info "Building SimpleLogin Android app..."
    
    # Ensure codebase directory exists (for submodule approach)
    if [[ ! -d "$CODEBASE_DIR" ]]; then
        log_error "Codebase directory not found at $CODEBASE_DIR"
        log_info "This may indicate a submodule initialization issue"
        return 1
    fi
    
    if [[ ! -d "$CODEBASE_DIR/SimpleLogin" ]]; then
        log_error "SimpleLogin directory not found at $CODEBASE_DIR/SimpleLogin"
        log_info "This may indicate an incomplete submodule checkout"
        return 1
    fi
    
    cd "$CODEBASE_DIR/SimpleLogin"
    
    # Make gradlew executable
    chmod +x gradlew

    # Configure release build to use debug signing for testing
    log_info "Configuring release build to use debug signing..."
    sed -i.bak 's/signingConfig signingConfigs.release/signingConfig signingConfigs.debug/' app/build.gradle

    # Clean and build release APK
    log_info "Running Gradle clean..."
    if ! ./gradlew --no-daemon clean; then
        log_error "Gradle clean failed"
        return 1
    fi

    log_info "Building F-Droid release APK..."
    if ! ./gradlew --no-daemon assembleFdroidRelease; then
        log_error "Gradle build failed"
        return 1
    fi
    
    # Find the built F-Droid APK
    local apk_path
    apk_path=$(find app/build/outputs/apk/fdroid/release -name "*.apk" | head -1)
    
    if [[ -z "$apk_path" || ! -f "$apk_path" ]]; then
        log_error "Built F-Droid APK not found in app/build/outputs/apk/fdroid/release/"
        return 1
    fi
    
    log_success "APK built successfully: $apk_path"
    
    # Create apk directory if it doesn't exist
    mkdir -p "$SCRIPT_DIR/apk"
    
    # Copy APK to standard location
    local apk_filename="simplelogin-fdroid-release.apk"
    local apk_dest="$SCRIPT_DIR/apk/$apk_filename"
    cp "$apk_path" "$apk_dest"
    
    log_success "APK copied to: $apk_dest"
    
    cd "$SCRIPT_DIR"
}

main() {
    log_info "Starting SimpleLogin Android app setup..."
    
    check_prerequisites || return 1
    # Use stock app without source modifications for real-world fidelity
    setup_environment || return 1
    build_app || return 1
    
    log_success "SimpleLogin Android app build completed successfully!"
    log_info "APK is ready for installation and testing."
}

# Run main function if script is executed directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
