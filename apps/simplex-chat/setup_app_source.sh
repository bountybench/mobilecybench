#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODEBASE_DIR="${SCRIPT_DIR}/codebase"
MULTIPLATFORM_DIR="${CODEBASE_DIR}/apps/multiplatform"
APK_DIR="${SCRIPT_DIR}/apk"
APK_UNSIGNED="${APK_DIR}/simplex-chat-unsigned.apk"
APK_SIGNED="${APK_DIR}/simplex-chat.apk"
KEYSTORE_FILE="$HOME/.android/debug.keystore"
AVAILABLE_ABIS=()

log()  { printf '[setup_app_source] %s\n' "$*"; }
warn() { printf '[setup_app_source][warn] %s\n' "$*" >&2; }
fail() { printf '[setup_app_source][error] %s\n' "$*" >&2; exit 1; }

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Required command '$1' not found in PATH"
}

default_host_abi() {
  local host_arch
  host_arch=$(uname -m)
  case "$host_arch" in
    x86_64|amd64) echo "x86_64" ;;
    arm64|aarch64) echo "arm64-v8a" ;;
    *) echo "armeabi-v7a" ;;
  esac
}

parse_requested_abis() {
  # Force ARM build; only arm64-v8a for now
  echo "arm64-v8a"
}

resolve_path() {
  python3 - "$1" <<'PY'
import os, sys
print(os.path.realpath(sys.argv[1]))
PY
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

find_apk() {
  local abi_filter="$1"
  if [[ -n "$abi_filter" ]]; then
    # Try to find APK matching the requested ABI
    local apk
    apk=$(find "$MULTIPLATFORM_DIR" -name "*${abi_filter}*release*.apk" -type f | head -n1)
    if [[ -n "$apk" ]]; then
      echo "$apk"
      return
    fi
    # Fallback: try without ABI in name (universal APK)
    apk=$(find "$MULTIPLATFORM_DIR" -name '*release*.apk' -type f ! -name '*-*-release*.apk' | head -n1)
    if [[ -n "$apk" ]]; then
      echo "$apk"
      return
    fi
  fi
  # Final fallback: any release APK
  find "$MULTIPLATFORM_DIR" -name '*release*.apk' -type f | head -n1
}

find_apksigner() {
  local sdk_home="$1"
  [[ -n "$sdk_home" ]] || fail "Android SDK home path is empty"
  [[ -d "$sdk_home" ]] || fail "Android SDK home is not a directory: $sdk_home"
  [[ -d "$sdk_home/build-tools" ]] || fail "build-tools directory not found at $sdk_home/build-tools"
  local tool="$(find "$sdk_home"/build-tools -name apksigner -type f 2>/dev/null | sort -V | tail -1)"
  [[ -n "$tool" ]] || fail "Could not find apksigner under $sdk_home/build-tools"
  [[ -f "$tool" ]] || fail "apksigner path is not a file: $tool"
  echo "$tool"
}

check_prereqs() {
  require_cmd python3
  require_cmd java
  require_cmd keytool
  require_cmd gunzip
  require_cmd unzip
  mkdir -p "$APK_DIR"
  [[ -d "$MULTIPLATFORM_DIR" ]] || fail "SimpleX source tree not found at $MULTIPLATFORM_DIR"
  chmod +x "$MULTIPLATFORM_DIR/gradlew"
}

available_abis() {
  # Force arm64-v8a ABI
  AVAILABLE_ABIS=(arm64-v8a)
}

prepare_native_libs_for_requested_abis() { :; }

ensure_native_libs() {
  local libs_root="${CODEBASE_DIR}/apps/multiplatform/common/src/commonMain/cpp/android/libs"
  [[ -d "$libs_root" ]] || fail "Expected native libs directory missing at $libs_root"

  local updated=0
  while IFS= read -r -d '' archive; do
    local target="${archive%.gz}"
    if [[ ! -f "$target" ]]; then
      log "Decompressing $(basename "$archive")"
      gunzip -c "$archive" > "$target"
      updated=1
    fi
  done < <(find "$libs_root" -name '*.so.gz' -print0)

  available_abis "$libs_root"

  if [[ $updated -eq 0 ]]; then
    log "Native libraries already present (${AVAILABLE_ABIS[*]})"
  else
    log "Prepared native libraries for ABIs: ${AVAILABLE_ABIS[*]}"
  fi
}

build_apk() {
  local sdk_home="$1"
  shift
  local abis=("$@")
  log "Building SimpleX Chat release APK (ABIs: ${abis[*]})"
  pushd "$MULTIPLATFORM_DIR" >/dev/null
  
  # Ensure local.properties exists with correct SDK path for Gradle
  local local_props="$MULTIPLATFORM_DIR/local.properties"
  echo "sdk.dir=$sdk_home" > "$local_props"
  
  export ANDROID_HOME="$sdk_home"
  export ANDROID_SDK_ROOT="$sdk_home"
  export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"

  local abi_property
  abi_property=$(IFS=,; echo "${abis[*]}")

  ./gradlew clean :android:assembleRelease -PsimplexAbiFilters="$abi_property"
  
  # Find the APK matching the first requested ABI (or any if multiple)
  local primary_abi="${abis[0]}"
  local built_apk
  built_apk=$(find_apk "$primary_abi")
  [[ -n "$built_apk" ]] || fail "Gradle build finished but no release APK was found for ABI: $primary_abi"
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
  log "Starting SimpleX Chat source build"
  check_prereqs
  local requested_abis=($(parse_requested_abis))
  AVAILABLE_ABIS=("${requested_abis[@]}")
  BUILD_ABIS=("${requested_abis[@]}")
  log "Building for ABIs: ${BUILD_ABIS[*]}"
  local sdk_home
  sdk_home=$(android_home)
  build_apk "$sdk_home" "${BUILD_ABIS[@]}"
  sign_apk "$sdk_home"
  log "Build complete"
}

main "$@"
