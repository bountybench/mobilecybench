#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
ANDROID_HOME="${HOME}/Android/Sdk"
source "$ROOT_DIR/utils/android.sh"

# Install on emulator
install_grocy() {
    echo "Installing Grocy Android on emulator..."

    # Check if emulator is running
    if ! adb devices | grep -q "device\|emulator"; then
        echo "ERROR: No Android emulator found."
        echo "Please start the emulator first."
        exit 1
    fi

    # Install APK
    APK_PATH="apk/grocy.apk"

    if [[ ! -f $APK_PATH ]]; then
        echo "ERROR: APK not found at $APK_PATH"
        echo "Please run ./setup_app_source.sh first to build the APK."
        exit 1
    fi

    adb install -r "$APK_PATH"
    echo "Grocy Android installed successfully."
}

# Launch Grocy
launch_grocy() {
    echo "Launching Grocy Android..."
    # Use monkey to launch the app (more robust than specifying exact activity)
    # Note: debug builds have .debug suffix
    adb shell monkey -p xyz.zedler.patrick.grocy.debug -c android.intent.category.LAUNCHER 1
    echo "Grocy Android should now be running on your emulator."
}

# Configure Grocy through UI automation
configure_grocy() {
    echo "Configuring Grocy Android through UI automation..."

    # Install uiautomator2 if not already installed
    pip3 install --break-system-packages -q uiautomator2 2>/dev/null || \
        pip3 install -q uiautomator2 2>/dev/null || \
        python3 -m pip install --break-system-packages -q uiautomator2

    # Run UI automation script
    python3 "$SCRIPT_DIR/setup_grocy_ui.py" \
        --server-url "http://10.0.2.2:8080" \
        --api-key "demo_api_key_for_testing"

    echo "Grocy Android configured successfully."
}

# Main function
main() {
    echo "Grocy Android Setup"
    echo "==================="

    echo "Setting up Grocy Android"

    install_grocy
    launch_grocy
    configure_grocy

    echo ""
    echo "Setup complete! Grocy is ready for testing."
}

# Run main function
main "$@"
