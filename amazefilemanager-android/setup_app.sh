#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(pwd)"
APK_URL="https://f-droid.org/repo/com.amaze.filemanager_117.apk"  # Version 3.8.4 from f-droid
APK_FILE="$SCRIPT_DIR/com.amaze.filemanager_117.apk"
PACKAGE_NAME="com.amaze.filemanager"

ANDROID_HOME="${HOME}/.android-sdk"
export PATH="${ANDROID_HOME}/platform-tools:$PATH"

# Check prerequisites
check_prerequisites() {
    echo "Checking prerequisites..."
    
    # Check Java
    if ! command -v java >/dev/null 2>&1; then
        echo "ERROR: Java not found. Please install Java."
        exit 1
    fi
    
    # Check Android SDK
    if [[ ! -d "$ANDROID_HOME" ]]; then
        echo "ERROR: Android SDK not found at $ANDROID_HOME"
        echo "Please run the Android emulator setup first."
        exit 1
    fi
    
    # Check for adb
    if ! command -v adb >/dev/null 2>&1; then
        echo "ERROR: adb not found. Please ensure your Android platform-tools are in your PATH."
        exit 1
    fi
    
    echo "Prerequisites verified."
}

download_and_install() {
   if [ -f "$APK_FILE" ]; then
        echo "Found existing Amaze File Manager APK. Skipping download."
   else
        echo "Downloading Amaze File Manager (v3.8.4) from $APK_URL ..."
        curl -L --fail --show-error -o "$APK_FILE" "$APK_URL"
   fi
   
   echo "Installing Amaze File Manager from $APK_FILE ..."
   adb uninstall "$PACKAGE_NAME" >/dev/null 2>&1 || true
   adb install -r -g "$APK_FILE"
}

launch_app() {
  echo "Launching $PACKAGE_NAME..."
  adb shell am start -n "$PACKAGE_NAME/com.amaze.filemanager.ui.activities.MainActivity"
  
  echo "Waiting for app to load..."
  sleep 2

  echo "Amaze File Manager installed and launched successfully."
  sleep 2

  echo "Exiting app."
  adb shell input keyevent KEYCODE_BACK
  adb shell input keyevent KEYCODE_BACK
}

main() {
  check_prerequisites
  download_and_install
  launch_app
  echo "Setup finished successfully."
}

main 