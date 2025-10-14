#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" 
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
source "$ROOT_DIR/utils/android.sh"

# Default Android SDK locations (macOS → Linux fallback)
if [ -z "${ANDROID_HOME:-}" ]; then
  if [ "$(uname -s)" = "Darwin" ]; then
    ANDROID_HOME="${HOME}/Library/Android/sdk"
  else
    ANDROID_HOME="${HOME}/.android-sdk"
  fi
fi

check_prerequisites() {
  echo "Checking prerequisites..."
 
  if ! command -v java >/dev/null 2>&1; then
    echo "ERROR: Java not found"
    exit 1
  fi

  if [ ! -d "$ANDROID_HOME" ]; then
    echo "ERROR: Android SDK not found at $ANDROID_HOME"
    echo "Please install or set ANDROID_HOME to a valid SDK path."
    exit 1
  fi

  echo "Prerequisites verified."
}

enter_codebase() {
  if [ ! -f "gradlew" ]; then
    [ -d "codebase" ] || { echo "ERROR: Gradle project not found"; exit 1; }
    cd codebase
  fi
  [ -x "./gradlew" ] || chmod +x ./gradlew
}

setup_environment() {
  echo "Setting up build environment..." 

  export ANDROID_HOME="$ANDROID_HOME"
  [ -d "$ANDROID_HOME/platform-tools" ] && export PATH="$ANDROID_HOME/platform-tools:$PATH"
  [ -d "$ANDROID_HOME/cmdline-tools/latest/bin" ] && export PATH="$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
  [ -d "$ANDROID_HOME/emulator" ] && export PATH="$ANDROID_HOME/emulator:$PATH"

  echo "Environment configured."
}
 
build_from_source() {  
  echo "Building Thunderbird from source..."
  
  # Set fixed JVM memory limits. 
  local jvm_max_gradle="4096m"
  local jvm_max_kotlin="1536m"
  echo "Setting JVM maximum memory for Gradle to ${jvm_max_gradle}"
  echo "Setting JVM maximum memory for Kotlin to ${jvm_max_kotlin}"

  echo "Starting build..."

  # Set environment variables to override JVM args as additional safety measure
  export GRADLE_OPTS="-Xmx${jvm_max_gradle} -Dorg.gradle.jvmargs=-Xmx${jvm_max_gradle}"
  
  ./gradlew assembleFullRelease \
    --no-daemon \
    -x lintVitalRelease \
    -x lintVitalFullRelease \
    -x lintVitalAnalyzeRelease \
    -x lintVitalAnalyzeFullRelease \
    -x lintVitalReportRelease \
    -x lintVitalReportFullRelease
   
  
  if [ $? -ne 0 ]; then
    echo "Build failed. Check error messages above."
    exit 1
  fi
   
  echo "Build completed successfully."

  # Clear intermediates to free space
  echo "Clearing intermediates to free up space..."
  rm -rf */build/intermediates 2>/dev/null || true
  rm -rf */build/tmp 2>/dev/null || true
}

sign_apk() {
    echo "Signing release APK..."

    KEYSTORE_FILE="$HOME/.android/debug.keystore"

    # Check if the debug keystore exists, and create it if it doesn't.
    if [ ! -f "$KEYSTORE_FILE" ]; then
        echo "Debug keystore not found. Generating a new one..."
        mkdir -p "$HOME/.android/"
        keytool -genkey -v -keystore "$KEYSTORE_FILE" \
                -alias androiddebugkey -keyalg RSA -keysize 2048 \
                -validity 10000 -storepass android -keypass android \
                -dname "CN=Android Debug, O=Android, C=US"
        echo "Debug keystore generated at $KEYSTORE_FILE"
    fi

    APK_UNSIGNED="app-thunderbird/build/outputs/apk/full/release/app-thunderbird-full-release-unsigned.apk"

    if [ ! -f "$APK_UNSIGNED" ]; then
        echo "ERROR: Unsigned APK not found at $APK_UNSIGNED"
        echo "Available APKs under build/outputs:"
        find . -path '*build/outputs/apk*' -name '*.apk' -type f 2>/dev/null | head -10 || true
        exit 1
    fi

    echo "Signing APK: $APK_UNSIGNED"

    # Use apksigner instead of deprecated jarsigner
    if [ -z "$ANDROID_HOME" ]; then
        echo "ERROR: ANDROID_HOME not set, cannot find apksigner"
        exit 1
    fi

    # Find the latest apksigner
    APKSIGNER=$(find "$ANDROID_HOME/build-tools" -name "apksigner" -type f | sort -r | head -n 1)

    # Fix path for Windows MinGW users
    if [ "$OSTYPE" = "msys" ]; then
        APKSIGNER=$(find "$ANDROID_HOME/build-tools" -name "apksigner.bat" -type f | sort -r | head -n 1)
    fi

    if [ ! -f "$APKSIGNER" ]; then
        echo "apksigner not found, falling back to jarsigner"
        jarsigner -verbose -sigalg SHA256withRSA -digestalg SHA256 -keystore "$HOME/.android/debug.keystore" -storepass android -keypass android "$APK_UNSIGNED" androiddebugkey
    else
        echo "Using apksigner: $APKSIGNER"
        "$APKSIGNER" sign --ks "$HOME/.android/debug.keystore" --ks-key-alias androiddebugkey --ks-pass pass:android --key-pass pass:android --v2-signing-enabled true "$APK_UNSIGNED"
    fi

    APK_SIGNED="${APK_UNSIGNED/-unsigned.apk/.apk}"
    if [ -f "$APK_UNSIGNED" ]; then
        mv "$APK_UNSIGNED" "$APK_SIGNED"
    fi

    echo "Signed APK: $APK_SIGNED"

    # Copy APK to ./apk/ directory for CI compatibility
    echo "Copying APK to ./apk/ directory..."
    APK_DIR="$SCRIPT_DIR/apk"
    mkdir -p "$APK_DIR"
    cp "$APK_SIGNED" "$APK_DIR/"
    echo "APK copied to: $APK_DIR/$(basename "$APK_SIGNED")"
}

install_thunderbird() { 
  echo "Installing on emulator/device..." 
  if ! command -v adb >/dev/null 2>&1; then
    echo "ERROR: adb not found. Ensure platform-tools are installed and on PATH."
    exit 1
  fi

  adb start-server >/dev/null 2>&1 || true
  
  # Check for device/emulator with more robust approach and timeout
  echo "Waiting for device/emulator (max 30s)..."
  timeout 30 bash -c 'until adb devices | grep -q "device\|emulator"; do sleep 1; done' || {
    echo "ERROR: No emulator/device available after waiting. Skipping installation."
    return 0
  }
  
  echo "Device/emulator detected!"
  
  APK_PATH="app-thunderbird/build/outputs/apk/full/release/app-thunderbird-full-release.apk"
  if [ ! -f "$APK_PATH" ]; then
    echo "ERROR: APK not found at $APK_PATH"
    echo "Available APKs under build/outputs:"
    find . -path '*build/outputs/apk*' -name '*.apk' -type f 2>/dev/null | head -10 || true
    exit 1
  fi

  echo "Installing APK: $APK_PATH"
  adb install -r -g "$APK_PATH"
  echo "App installed successfully."
}

synch_with_server() {
  echo "Syncing with server via uiautomator2..."
  
  # Check for device/emulator with timeout
  echo "Waiting for device/emulator (max 30s)..."
  timeout 30 bash -c 'until adb devices | grep -q "device\|emulator"; do sleep 1; done' || {
    echo "ERROR: No emulator/device available after waiting. Skipping sync step."
    return 0
  }
  
  cd "$SCRIPT_DIR"
  pip install -q uiautomator2
  USERNAME="$(jq -r '.username' metadata.json)"
  PASSWORD="$(jq -r '.password' metadata.json)"
  
  # In CI environment, use a timeout for the sync operation
  if [ -n "${CI:-}" ]; then
    echo "Running sync in CI environment (with 60s timeout)..."
    timeout 60 python synch_app.py --username "$USERNAME" --password "$PASSWORD" || {
      echo "WARNING: Sync operation timed out or failed in CI environment"
      return 0
    }
  else
    python synch_app.py --username "$USERNAME" --password "$PASSWORD"
  fi
}

launch_thunderbird() {
  echo "Launching Thunderbird..." 
  # Launch with error handling
  echo "Launching app with adb..."
  adb_launch_activity "net.thunderbird.android/com.fsck.k9.activity.MessageList" || {
    echo "WARNING: Failed to launch Thunderbird app"
    return 0
  }
  
  echo "App launched successfully"
}

main() {
  echo "Thunderbird Android Setup"
  check_prerequisites
  enter_codebase
  setup_environment
  build_from_source
  sign_apk
  
  # commented out for CI 
  # install_thunderbird
  # launch_thunderbird
  # synch_with_server
  echo "Setup complete!"
}

main "$@"
