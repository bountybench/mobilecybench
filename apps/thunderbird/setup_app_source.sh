#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANDROID_HOME="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"

check_prerequisites() {
  command -v java >/dev/null 2>&1 || { echo "ERROR: Java not found"; exit 1; }
  command -v adb  >/dev/null 2>&1 || { echo "ERROR: adb not found"; exit 1; }
  [[ -d "$ANDROID_HOME" ]] || { echo "ERROR: Android SDK not found at $ANDROID_HOME"; exit 1; }
}

enter_codebase() {
  if [[ ! -f "gradlew" ]]; then
    [[ -d "codebase" ]] || { echo "ERROR: Gradle project not found"; exit 1; }
    cd codebase
  fi
  [[ -x "./gradlew" ]] || chmod +x ./gradlew
}

setup_environment() {
  export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
  echo "sdk.dir=$ANDROID_HOME" > local.properties
}

build_from_source() {
  ./gradlew --no-daemon clean assembleDebug \
    -Dorg.gradle.jvmargs="-Xmx4096m -XX:+HeapDumpOnOutOfMemoryError -Dfile.encoding=UTF-8"
}

install_thunderbird() {
  adb devices | grep -q "device\|emulator" || { echo "ERROR: No emulator found"; exit 1; }
  APK_PATH="app-thunderbird/build/outputs/apk/full/debug/app-thunderbird-full-debug.apk"
  [[ -f "$APK_PATH" ]] || { echo "ERROR: APK not found at $APK_PATH"; exit 1; }
  adb install "$APK_PATH"
}

synch_with_server() {
  cd "$SCRIPT_DIR"
  pip install -q uiautomator2
  USERNAME="$(jq -r '.username' metadata.json)"
  PASSWORD="$(jq -r '.password' metadata.json)"
  python synch_app.py --username "$USERNAME" --password "$PASSWORD"
}

launch_thunderbird() {
  adb shell monkey -p net.thunderbird.android -c android.intent.category.LAUNCHER 1
}

main() {
  echo "Thunderbird Android Setup"
  check_prerequisites
  enter_codebase
  setup_environment
  build_from_source
  install_thunderbird
  synch_with_server
  launch_thunderbird
  echo "Setup complete!"
}

main "$@"
