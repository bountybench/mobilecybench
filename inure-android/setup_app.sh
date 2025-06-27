#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(pwd)"
APK_URL="https://github.com/Hamza417/Inure/releases/download/build95/app-github-release.apk"
APK_FILE="$SCRIPT_DIR/Inurev95.apk"
PACKAGE_NAME="app.simple.inure"

ANDROID_HOME="${HOME}/.android-sdk"
export PATH="${ANDROID_HOME}/platform-tools:$PATH"

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
    
    # Check for adb
    if ! command -v adb >/dev/null 2>&1; then
        echo "ERROR: adb not found. Please ensure your Android platform-tools are in your PATH."
        exit 1
    fi
    
    echo "Prerequisites verified."
}

download_and_install() {
   if [ -f "$APK_FILE" ]; then
        echo "Found existing Inure APK. Skipping download."
   else
        echo "Downloading Inure (Build 95) from $APK_URL ..."
        curl -L --fail --show-error -o "$APK_FILE" "$APK_URL"
   fi
   
   echo "Installing Inure from $APK_FILE ..."
   adb uninstall "$PACKAGE_NAME" >/dev/null 2>&1 || true
   adb install -r "$APK_FILE"
}

launch_app() {
  echo "Launching $PACKAGE_NAME..."
  adb shell am start -n "$PACKAGE_NAME/.activities.app.MainActivity"
  
  echo "Waiting for app to load..."
  sleep 2

  echo "Inure (Build 95) installed and launched successfully."
  sleep 2

  echo "Exiting Inure app."
  adb shell input keyevent KEYCODE_BACK
}

main() {
  check_prerequisites
  download_and_install
  launch_app
  echo "Setup finished successfully."
}

main