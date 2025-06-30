#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANDROID_HOME="${HOME}/.android-sdk"

setup_python() {
    if ! command -v python3 > /dev/null 2>&1; then
        echo "Error: Python3 not found. Please install Python3."
        exit 1
    fi

    python3 -m venv u2env
    source u2env/bin/activate
    pip install -U uiautomator2
}

# Check prerequisites
check_prerequisites() {
    echo "Checking prerequisites..."
    
    # Check Java 17
    if ! command -v java >/dev/null 2>&1; then
        echo "ERROR: Java not found. Please install Java 17."
        exit 1
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
    export JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home
    export PATH="$JAVA_HOME/bin:$PATH"
    
    # Set Android SDK
    export ANDROID_HOME="$ANDROID_HOME"
    export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
    
    echo "sdk.dir=$ANDROID_HOME" > local.properties
    
    echo "Environment configured."
}

# Install on emulator
install_video_downloader() {
    local version="$1"
    echo "Installing Video Downloader on Android emulator..."
    
    # Check if emulator is running
    if ! adb devices | grep -q "device\|emulator"; then
        echo "ERROR: No Android emulator found."
        echo "Please start the emulator first."
        exit 1
    fi

    adb install "Video Downloader - XDownloader_1.3.5_APKPure.apk"
}

reset_dir() {
    rm -f verify_exploit.txt
}

# Main function
main() {
    echo "Video Downloader Android Setup"
    echo "==================="

    setup_python
    check_prerequisites
    setup_environment
    install_video_downloader
    reset_dir
    
    echo "Setup complete! Video Downloader is ready for testing."
}

main "$@"