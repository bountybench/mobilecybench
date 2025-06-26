#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(pwd)"
APK_URL="https://www.apkmirror.com/wp-content/themes/APKMirror/download.php?id=5517105&key=6fea3dd3af25f7ec860f624ffa7a9ea84ff16ca1&forcebaseapk=true"
APK_FILE="$SCRIPT_DIR/ColorOS_45.10.3.4.1.apk"
PACKAGE_NAME="com.heytap.browser"

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
    
    echo "Prerequisites verified."
}

download_and_install() {
   echo "Downloading apk from $APK_URL ..." # curl and download apk
   curl -L --fail --show-error \
    -A "Mozilla/5.0 (X11; Linux x86_64)" \
    -H "Referer: https://www.apkmirror.com/apk/heytap/internet-browser-3/" \
    -o "$APK_FILE" \
    "$APK_URL"
   echo "Installing apk from $APK_FILE ..."
   adb uninstall "$PACKAGE_NAME" >/dev/null 2>&1 || true
   adb install -r "$APK_FILE"
 }

launch_app() {
  echo "Launching $PACKAGE_NAME..."
  adb shell monkey -p "$PACKAGE_NAME" -c android.intent.category.LAUNCHER 1

  echo "Waiting for app to load..."
  sleep 8

  echo "Clicking to home screen..."
  adb shell input tap 538 1641

  echo "Waiting for browser to fully load..."
  sleep 2

  echo "ColorOS Browser installed and launched successfully."
}

main() {
  check_prerequisites
  download_and_install
  launch_app
  echo "Setup finished successfully."
}

main
