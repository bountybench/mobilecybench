#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
ANDROID_HOME="${HOME}/.android-sdk"
source "$ROOT_DIR/utils/android.sh"

# Check prerequisites
check_prerequisites() {
    echo "Checking prerequisites..."
    
    # Check Java 17
    if ! command -v java >/dev/null 2>&1; then
        echo "ERROR: Java not found. Please install Java 17."
        exit 1
    fi

    # Check Node.js
    if ! command -v node >/dev/null 2>&1; then
        echo "ERROR: Node.js not found. Please install Node.js v24+."
        exit 1
    fi
    
    # Check Node.js version compatibility
    NODE_VERSION=$(node -v | sed 's/v//')
    NODE_MAJOR=$(echo "$NODE_VERSION" | cut -d. -f1)
    if [[ $NODE_MAJOR -lt 24 ]]; then
        echo "WARNING: Node.js $NODE_VERSION detected, but Brave requires v24+."
        echo "Falling back to APK download instead of source build..."
        exec "$SCRIPT_DIR/setup_app_apklink.sh"
    fi

    # Check npm
    if ! command -v npm >/dev/null 2>&1; then
        echo "ERROR: npm not found. Please install npm."
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
    
    export ANDROID_HOME
    export PATH="$ANDROID_HOME/tools:$ANDROID_HOME/tools/bin:$ANDROID_HOME/platform-tools:$PATH"
    export JAVA_OPTS="-Xmx10G -Xms1G"
    
    # Navigate to codebase directory
    cd "$SCRIPT_DIR/codebase"
    
    echo "Environment setup complete."
}

# Build Brave for Android
build_brave() {
    echo "Building Brave for Android..."
    
    # Install dependencies and sync
    echo "Installing npm dependencies..."
    npm install
    echo "Initializing Brave build environment..."
    npm run init
    echo "Syncing Brave for Android..."
    npm run sync -- --target_os=android
    
    # Build for Android (release build)
    echo "Building Brave APK..."
    npm run build -- --target_os=android --target_arch=arm64 --target_android_output_format=apk
    
    # Find the built APK
    APK_PATH=$(find src/out -name "*.apk" | head -1)
    if [[ -z "$APK_PATH" ]]; then
        echo "ERROR: APK not found after build"
        exit 1
    fi
    
    echo "APK built successfully at: $APK_PATH"
}

# Copy APK to standard location
copy_apk() {
    echo "Copying APK to standard location..."
    
    # Create apk directory if it doesn't exist
    mkdir -p "$SCRIPT_DIR/apk"
    
    # Find and copy the APK
    APK_PATH=$(find "$SCRIPT_DIR/codebase/src/out" -name "*.apk" | head -1)
    if [[ -z "$APK_PATH" ]]; then
        echo "ERROR: Could not find built APK"
        exit 1
    fi
    
    cp "$APK_PATH" "$SCRIPT_DIR/apk/brave.apk"
    echo "APK copied to: $SCRIPT_DIR/apk/brave.apk"
}

# Main execution
main() {
    echo "Starting Brave Android build process..."
    
    check_prerequisites
    setup_environment
    build_brave
    copy_apk
    
    echo "Brave Android APK build completed successfully!"
}

main "$@"