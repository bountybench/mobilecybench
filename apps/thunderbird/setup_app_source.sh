#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" 
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")" 

# Default Android SDK locations (macOS → Linux fallback)
if [[ -z "${ANDROID_HOME:-}" ]]; then
  if [[ "$(uname -s)" == "Darwin" ]]; then
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

  if [[ ! -d "$ANDROID_HOME" ]]; then
    echo "ERROR: Android SDK not found at $ANDROID_HOME"
    echo "Please install or set ANDROID_HOME to a valid SDK path."
    exit 1
  fi

  echo "Prerequisites verified."
}

enter_codebase() {
  if [[ ! -f "gradlew" ]]; then
    [[ -d "codebase" ]] || { echo "ERROR: Gradle project not found"; exit 1; }
    cd codebase
  fi
  [[ -x "./gradlew" ]] || chmod +x ./gradlew
}

setup_environment() {
  echo "Setting up build environment..." 

  export ANDROID_HOME="$ANDROID_HOME"
  [[ -d "$ANDROID_HOME/platform-tools" ]] && export PATH="$ANDROID_HOME/platform-tools:$PATH"
  [[ -d "$ANDROID_HOME/cmdline-tools/latest/bin" ]] && export PATH="$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
  [[ -d "$ANDROID_HOME/emulator" ]] && export PATH="$ANDROID_HOME/emulator:$PATH"

  echo "sdk.dir=$ANDROID_HOME" > local.properties
  echo "Environment configured."
}

build_from_source() {  
  echo "Building Thunderbird from source..."
  # ./gradlew --no-daemon clean --parallel \
  #   :app-thunderbird:assembleFullDebug \
  #   -Dorg.gradle.jvmargs="-Xmx4096m -XX:+HeapDumpOnOutOfMemoryError -Dfile.encoding=UTF-8"

  # hopefully CI safe approach 
  ./gradlew \
    :app-thunderbird:assembleFullDebug \
    -Dorg.gradle.jvmargs="-Dfile.encoding=UTF-8 -Xms512m -Xmx3g -XX:MaxMetaspaceSize=512m -XX:+HeapDumpOnOutOfMemoryError -XX:+UseG1GC" \
    -Dkotlin.daemon.jvm.options="-Dfile.encoding=UTF-8,-Xms256m,-Xmx2g,-XX:+UseG1GC" \
    -Dorg.gradle.workers.max=2 \
    --stacktrace --build-cache
  echo "Build completed successfully."
}

install_thunderbird() { 
  echo "Installing on emulator/device..." 
  if ! command -v adb >/dev/null 2>&1; then
    echo "ERROR: adb not found. Ensure platform-tools are installed and on PATH."
    exit 1
  fi

  adb start-server >/dev/null 2>&1 || true
  if ! adb devices | grep -q "device\|emulator"; then
    echo "ERROR: No emulator/device found. Please start one first."
    exit 1
  fi

  APK_PATH="app-thunderbird/build/outputs/apk/full/debug/app-thunderbird-full-debug.apk"
  if [[ ! -f "$APK_PATH" ]]; then
    echo "ERROR: APK not found at $APK_PATH"
    echo "Available APKs under build/outputs:"
    find . -path '*build/outputs/apk*' -name '*.apk' -type f 2>/dev/null | head -10 || true
    exit 1
  fi

  adb install -r -g "$APK_PATH"
  echo "App installed successfully."
}

synch_with_server() {
  echo "Syncing with server via uiautomator2..."
  cd "$SCRIPT_DIR"
  pip install -q uiautomator2
  USERNAME="$(jq -r '.username' metadata.json)"
  PASSWORD="$(jq -r '.password' metadata.json)"
  python synch_app.py --username "$USERNAME" --password "$PASSWORD" 
}

launch_thunderbird() {
  echo "Launching Thunderbird..."
  # adb shell monkey -p net.thunderbird.android -c android.intent.category.LAUNCHER 1 
  adb shell monkey -p net.thunderbird.android.debug -c android.intent.category.LAUNCHER 1 
}

main() {
  echo "Thunderbird Android Setup"
  check_prerequisites
  enter_codebase
  setup_environment
  build_from_source
  install_thunderbird
  launch_thunderbird
  synch_with_server
  echo "Setup complete!"
}

main "$@"
