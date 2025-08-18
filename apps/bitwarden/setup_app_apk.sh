#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANDROID_HOME="${HOME}/.android-sdk"
BITWARDEN_PKG="com.x8bit.bitwarden.dev"

echo === RUNNING setup_app_apk.sh ===

# Install on emulator
install_bitwarden() {
    echo "Installing Bitwarden on Android emulator..."

    # Check jq is available
    if ! command -v jq >/dev/null 2>&1; then
        echo "ERROR: jq is required to parse metadata.json. Please install jq and retry."
        exit 1
    fi

    # Check if emulator is running
    if ! adb devices | grep -w "device" | grep -v "List" >/dev/null; then
        echo "ERROR: No Android emulator found."
        echo "Please start the emulator first."
        exit 1
    fi

    # Install APK with link
    metadata="${SCRIPT_DIR}/metadata.json"
    APK_PATH="${SCRIPT_DIR}/bitwarden.apk"
    download_link=$(jq -r '.download_link' "$metadata")
    if [[ ! -f "$APK_PATH" ]]; then
        echo "Downloading using download link for version $version: $download_link"
        curl -L -o "$APK_PATH" "$download_link"
    fi

    if [[ ! -f $APK_PATH ]]; then
        echo "ERROR: APK not found at $APK_PATH"
        exit 1
    fi

    adb install "$APK_PATH"
    echo "Bitwarden installed successfully."
}

# Launch Bitwarden directly
launch_bitwarden() {
    echo "Launching Bitwarden..."
    
    # Launch Bitwarden using package name
    adb shell monkey -p $BITWARDEN_PKG -c android.intent.category.LAUNCHER 1
    
    # Verify launch
    sleep 2
    if adb shell dumpsys window | grep -q "mCurrentFocus.*$BITWARDEN_PKG"; then
        echo "Successfully launched Bitwarden!"
        return 0
    else
        echo "Bitwarden may not have launched properly."
        echo "Please check your emulator or device - Bitwarden should be installed."
        return 1
    fi
}

# Main function
main() {
    echo "Bitwarden Android Setup"
    echo "======================="
    
    echo "Installing Bitwarden Android from APK"
    
    install_bitwarden
    
    echo ""
    echo "=========================================="
    echo "Setup complete! Bitwarden has been installed."
    echo "=========================================="
    echo ""
    
    if launch_bitwarden; then
        echo "Bitwarden is now running and ready for mobile security testing!"
    else
        echo "Please manually launch Bitwarden from your emulator or device."
        echo "You can also try running: adb shell monkey -p $BITWARDEN_PKG -c android.intent.category.LAUNCHER 1"
    fi
    
    echo ""
    echo "Bitwarden setup completed successfully!"
    echo === FINISHED setup_app_apk.sh ===
}

# Run main function
main 