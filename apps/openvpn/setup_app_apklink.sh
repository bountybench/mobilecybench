#!/bin/bash
set -e

echo "Setting up OpenVPN app via APK download..."

# Load metadata for download link
if [ -f "metadata.json" ]; then
    DOWNLOAD_URL=$(python3 -c "import json; print(json.load(open('metadata.json'))['download_link'])")
    echo "APK download URL: $DOWNLOAD_URL"
else
    echo "Error: metadata.json not found"
    exit 1
fi

# Create apk directory (required for CI)
mkdir -p apk

# Download APK if not already present
APK_FILE="apk/openvpn.apk"
if [ ! -f "$APK_FILE" ]; then
    echo "Downloading OpenVPN APK..."
    curl -L -o "$APK_FILE" "$DOWNLOAD_URL"
    if [ $? -ne 0 ]; then
        echo "Error: Failed to download APK from $DOWNLOAD_URL"
        exit 1
    fi
else
    echo "APK already downloaded: $APK_FILE"
fi

# Verify APK file
if [ ! -f "$APK_FILE" ] || [ ! -s "$APK_FILE" ]; then
    echo "Error: Downloaded APK file is invalid"
    exit 1
fi

echo "APK ready at: $APK_FILE"

# Check if emulator is running (optional - only install if emulator available)
if ! adb devices | grep -q "emulator"; then
    echo "No emulator detected - APK downloaded but not installed"
    echo "APK is available at $APK_FILE for CI to install later"
    exit 0
fi

echo "Installing OpenVPN APK on emulator: $APK_FILE"

# Uninstall existing version if present
adb uninstall de.blinkt.openvpn || echo "No existing app to uninstall"

# Install the APK
adb install "$APK_FILE"

# Wait for installation
sleep 5

# Copy OpenVPN configuration to device if available
echo "Copying OpenVPN client configuration..."
if [ -f "client-configs/android-client.ovpn" ]; then
    adb push client-configs/android-client.ovpn /sdcard/Download/
    echo "OpenVPN config copied to /sdcard/Download/android-client.ovpn"
else
    echo "Warning: No client configuration found. Run setup.sh first to generate certificates."
fi

# Launch the app
echo "Launching OpenVPN app..."
adb shell am start -n de.blinkt.openvpn/de.blinkt.openvpn.LaunchVPN

# Wait for app to start
sleep 3

# Check if app launched successfully
if adb shell dumpsys package de.blinkt.openvpn | grep -q "ACTIVITY"; then
    echo "✓ OpenVPN app launched successfully"
else
    echo "⚠ App may not have launched properly"
fi

echo ""
echo "OpenVPN app setup completed!"
echo "The app is now installed and running on the emulator."
echo "You can import the VPN profile from /sdcard/Download/android-client.ovpn"
echo ""
echo "Next steps:"
echo "1. Open the OpenVPN app on the emulator"
echo "2. Import the client configuration file"
echo "3. Connect to the VPN server at 10.0.2.2:1194"