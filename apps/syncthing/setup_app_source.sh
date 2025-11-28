#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODEBASE_DIR="${SCRIPT_DIR}/codebase"
APK_DIR="${SCRIPT_DIR}/apk"
APK_UNSIGNED="${APK_DIR}/syncthing-unsigned.apk"
APK_SIGNED="${APK_DIR}/syncthing.apk"
KEYSTORE_FILE="$HOME/.android/debug.keystore"

log()  { printf '[setup_app_source] %s\n' "$*"; }
warn() { printf '[setup_app_source][warn] %s\n' "$*" >&2; }
fail() { printf '[setup_app_source][error] %s\n' "$*" >&2; exit 1; }

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Required command '$1' not found in PATH"
}

android_home() {
  if [[ -n "${ANDROID_HOME:-}" ]]; then
    if [[ ! -d "$ANDROID_HOME" ]]; then
      fail "ANDROID_HOME is set to '$ANDROID_HOME' but this is not a valid directory"
    fi
    echo "$ANDROID_HOME"
    return
  fi

  local default_home="$HOME/.android-sdk"
  if [[ ! -d "$default_home" ]]; then
    fail "Android SDK not found. Set ANDROID_HOME or install the SDK at $default_home"
  fi
  echo "$default_home"
}

ensure_keystore() {
  if [[ -f "$KEYSTORE_FILE" ]]; then
    return
  fi

  log "Generating debug keystore at $KEYSTORE_FILE"
  mkdir -p "$(dirname "$KEYSTORE_FILE")"
  keytool -genkey -v -keystore "$KEYSTORE_FILE" \
    -alias androiddebugkey -keyalg RSA -keysize 2048 \
    -validity 10000 -storepass android -keypass android \
    -dname "CN=Android Debug, O=Android, C=US"
}

find_apksigner() {
  local sdk_home="$1"
  [[ -n "$sdk_home" ]] || fail "Android SDK home path is empty"
  [[ -d "$sdk_home" ]] || fail "Android SDK home is not a directory: $sdk_home"
  [[ -d "$sdk_home/build-tools" ]] || fail "build-tools directory not found at $sdk_home/build-tools"
  local tool
  tool=$(find "$sdk_home"/build-tools -name apksigner -type f 2>/dev/null | sort -V | tail -1)
  [[ -n "$tool" ]] || fail "Could not find apksigner under $sdk_home/build-tools"
  [[ -f "$tool" ]] || fail "apksigner path is not a file: $tool"
  echo "$tool"
}

check_prereqs() {
  require_cmd java
  require_cmd keytool
  mkdir -p "$APK_DIR"
  [[ -d "$CODEBASE_DIR" ]] || fail "Syncthing source tree not found at $CODEBASE_DIR"
  chmod +x "$CODEBASE_DIR/gradlew"
}

build_apk() {
  local sdk_home="$1"
  log "Building Syncthing-Fork release APK"
  pushd "$CODEBASE_DIR" >/dev/null

  local local_props="$CODEBASE_DIR/local.properties"
  echo "sdk.dir=$sdk_home" > "$local_props"

  export ANDROID_HOME="$sdk_home"
  export ANDROID_SDK_ROOT="$sdk_home"
  export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"

  ./gradlew clean :app:assembleRelease

  local built_apk
  built_apk=$(find "$CODEBASE_DIR/app/build/outputs/apk/release" -name "*-universal-release-unsigned.apk" -type f | head -n1)

  [[ -n "$built_apk" ]] || fail "Gradle build finished but no release APK was found"
  cp "$built_apk" "$APK_UNSIGNED"
  popd >/dev/null
  log "Unsigned APK copied to $APK_UNSIGNED (from: $(basename "$built_apk"))"
}

sign_apk() {
  local sdk_home="$1"
  ensure_keystore
  local apksigner
  apksigner=$(find_apksigner "$sdk_home")
  log "Signing APK with $apksigner"
  "$apksigner" sign --ks "$KEYSTORE_FILE" --ks-key-alias androiddebugkey \
    --ks-pass pass:android --key-pass pass:android --v1-signing-enabled true \
    --v2-signing-enabled true --out "$APK_SIGNED" "$APK_UNSIGNED"
  "$apksigner" verify "$APK_SIGNED"
  log "Signed APK ready at $APK_SIGNED"
}

main() {
  log "Starting Syncthing-Fork source build"
  check_prereqs
  local sdk_home
  sdk_home=$(android_home)
  build_apk "$sdk_home"
  sign_apk "$sdk_home"
  log "Build complete"
}

main "$@"
