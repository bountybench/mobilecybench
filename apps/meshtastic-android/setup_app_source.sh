#!/usr/bin/env bash
# Build Meshtastic Android app from source
# This script builds the vulnerable version (2.5.20) of Meshtastic-Android
# CVE-2025-52883: Forged DMs with no PKC show up as encrypted

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="meshtastic-android"
APK_DIR="$SCRIPT_DIR/apk"
CODEBASE_DIR="$SCRIPT_DIR/codebase"

LOG_PREFIX="[setup_app_source]"
info() { printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn() { printf '%s[warn] %s\n' "$LOG_PREFIX" "$*"; }
error() { printf '%s[error] %s\n' "$LOG_PREFIX" "$*"; exit 1; }

setup_environment() {
    info "Setting up build environment..."

    # Set JAVA_HOME (prefer Android Studio's bundled JBR, then system paths)
    if [[ -z "${JAVA_HOME:-}" ]]; then
        # Try Android Studio's bundled JBR first (common for local development)
        if [[ -d "$HOME/Downloads/android-studio-2025.2.1.7-linux/android-studio/jbr" ]]; then
            export JAVA_HOME="$HOME/Downloads/android-studio-2025.2.1.7-linux/android-studio/jbr"
        elif [[ -d "$HOME/.local/share/JetBrains/Toolbox/apps/AndroidStudio/*/jbr" ]]; then
            export JAVA_HOME=$(find "$HOME/.local/share/JetBrains/Toolbox/apps/AndroidStudio" -name "jbr" -type d 2>/dev/null | head -1)
        # Homebrew OpenJDK (macOS)
        elif [[ -d "/opt/homebrew/opt/openjdk@17" ]]; then
            export JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home
        # System OpenJDK (Linux)
        elif [[ -d "/usr/lib/jvm/java-17-openjdk" ]]; then
            export JAVA_HOME=/usr/lib/jvm/java-17-openjdk
        elif [[ -d "/usr/lib/jvm/java-17-openjdk-amd64" ]]; then
            export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
        # CI environment (check common CI paths)
        elif [[ -d "/usr/local/lib/android/sdk/jbr" ]]; then
            export JAVA_HOME=/usr/local/lib/android/sdk/jbr
        else
            # Fallback: try to find java in PATH and extract JAVA_HOME
            if command -v java >/dev/null 2>&1; then
                warn "Could not find Java via known paths. Attempting to detect from java command."
                JAVA_BIN=$(command -v java)
                # Resolve symlinks
                while [[ -L "$JAVA_BIN" ]]; do
                    JAVA_BIN=$(readlink "$JAVA_BIN")
                done
                export JAVA_HOME=$(dirname "$(dirname "$JAVA_BIN")")
            else
                error "Java not found. Please install Java 17 or later, or set JAVA_HOME environment variable."
            fi
        fi
        info "Using JAVA_HOME: $JAVA_HOME"
    else
        info "Using pre-set JAVA_HOME: $JAVA_HOME"
    fi

    export PATH="$JAVA_HOME/bin:$PATH"

    # Verify Java is now available
    if ! command -v java >/dev/null 2>&1; then
        error "Java not found in PATH after setting JAVA_HOME. Please check your Java installation."
    fi

    # Set ANDROID_HOME (check if already set, otherwise try common locations)
    if [[ -z "${ANDROID_HOME:-}" ]]; then
        if [[ -d "$HOME/Android/Sdk" ]]; then
            export ANDROID_HOME="$HOME/Android/Sdk"
        elif [[ -d "/usr/local/lib/android/sdk" ]]; then
            export ANDROID_HOME="/usr/local/lib/android/sdk"
        elif [[ -d "${HOME}/.android-sdk" ]]; then
            export ANDROID_HOME="${HOME}/.android-sdk"
        elif [[ -n "${ANDROID_SDK_ROOT:-}" ]]; then
            export ANDROID_HOME="$ANDROID_SDK_ROOT"
        else
            error "Android SDK not found. Please set ANDROID_HOME environment variable."
        fi
        info "Using ANDROID_HOME: $ANDROID_HOME"
    else
        info "Using pre-set ANDROID_HOME: $ANDROID_HOME"
    fi

    # Verify Android SDK exists
    if [[ ! -d "$ANDROID_HOME" ]]; then
        error "Android SDK not found at $ANDROID_HOME"
    fi

    export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"

    # Create local.properties for Gradle
    echo "sdk.dir=$ANDROID_HOME" > "$CODEBASE_DIR/local.properties"

    info "Environment configured."
}

build_meshtastic() {
    info "Building Meshtastic-Android from source..."

    # Ensure codebase directory exists
    if [ ! -d "$CODEBASE_DIR" ]; then
        error "Codebase directory not found at $CODEBASE_DIR"
    fi

    cd "$CODEBASE_DIR"

    # Submodule is already at the correct vulnerable version (2.5.20)
    # Initialize nested submodules (protobuf definitions)
    info "Initializing protobuf submodules..."
    git submodule update --init --recursive

    # Clean previous builds
    info "Cleaning previous builds..."
    ./gradlew clean || true

    # Build release APK
    info "Building release APK (this may take several minutes)..."
    ./gradlew assembleRelease

    # Find the built APK (using F-Droid variant, which has no Google dependencies)
    BUILT_APK=$(find app/build/outputs/apk/fdroid/release -name "*.apk" | head -1)

    if [ -z "$BUILT_APK" ]; then
        error "Could not find built APK"
    fi

    # Create APK directory
    mkdir -p "$APK_DIR"

    # Copy APK to standard location
    cp "$BUILT_APK" "$APK_DIR/$APP_NAME.apk"

    info "APK built successfully: $APK_DIR/$APP_NAME.apk"
    info "APK size: $(du -h "$APK_DIR/$APP_NAME.apk" | cut -f1)"
}

main() {
    info "Meshtastic Android Setup"
    echo "============================"

    setup_environment
    build_meshtastic

    echo ""
    echo "=========================================="
    info "Build complete! Meshtastic-Android is ready to be installed"
    echo "=========================================="
    echo ""
}

main "$@"
