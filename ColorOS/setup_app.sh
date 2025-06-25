#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(pwd)"
APK_URL="https://www.apkmirror.com/wp-content/themes/APKMirror/download.php?id=5517105&key=bd1c2f68d231f7ccdef1c80107fff9a4e2016227&forcebaseapk=true"
APK_FILE="$SCRIPT_DIR/ColorOS_45.10.3.4.1.apk"
PACKAGE_NAME="com.heytap.browser"

export PATH="${ANDROID_HOME:-$HOME/.android-sdk}/platform-tools:$PATH"

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

download_and_install() {
   echo "Downloading $APK_FILE ..."
   curl -L --fail --show-error \
    -A "Mozilla/5.0 (X11; Linux x86_64)" \
    -H "Referer: https://www.apkmirror.com/apk/heytap/internet-browser-3/" \
    -o "$APK_FILE" \
    "$APK_URL"
   echo "Installing $APK_FILE ..."
   adb uninstall "$PACKAGE_NAME" >/dev/null 2>&1 || true
   adb install -r "$APK_FILE"
 }

launch_app() {
  echo "Launching $PACKAGE_NAME ..."
  adb shell monkey -p "$PACKAGE_NAME" -c android.intent.category.LAUNCHER 1
}

main() {
  check_prerequisites
  download_and_install
  launch_app
  echo "Setup finished successfully."
}

main
