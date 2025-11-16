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

android_home() {
  if [[ -n "${ANDROID_HOME:-}" && -d "$ANDROID_HOME" ]]; then
    echo "$ANDROID_HOME"
    return
  fi

  local default_home="$HOME/.android-sdk"
  [[ -d "$default_home" ]] || fail "Android SDK not found. Set ANDROID_HOME or install the SDK at $default_home"
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
  find "$MULTIPLATFORM_DIR" -name '*release*.apk' -type f | head -n1
}

find_apksigner() {
  local sdk_home="$1"
  local tool="$(find "$sdk_home"/build-tools -name apksigner -type f 2>/dev/null | sort | tail -1)"
  [[ -n "$tool" ]] || fail "Could not find apksigner under $sdk_home/build-tools"
  echo "$tool"
}

check_prereqs() {
  require_cmd java
  require_cmd keytool
  require_cmd gunzip
  mkdir -p "$APK_DIR"
  [[ -d "$MULTIPLATFORM_DIR" ]] || fail "SimpleX source tree not found at $MULTIPLATFORM_DIR"
  chmod +x "$MULTIPLATFORM_DIR/gradlew"
}

available_abis() {
  local libs_root="$1"
  AVAILABLE_ABIS=()
  while IFS= read -r line; do
    [[ -n "$line" ]] && AVAILABLE_ABIS+=("$line")
  done < <(
    find "$libs_root" -mindepth 1 -maxdepth 1 -type d -print0 \
      | xargs -0 -I{} bash -c '
          shopt -s nullglob;
          dir="$1";
          abi=$(basename "$dir");
          files=("$dir"/*.so "$dir"/*.so.gz);
          if [[ ${#files[@]} -gt 0 ]]; then
            echo "$abi"
          fi
        ' _ {}
  )
  AVAILABLE_ABIS=($(printf "%s\n" "${AVAILABLE_ABIS[@]}" | awk 'NF' | sort -u))
  if [[ ${#AVAILABLE_ABIS[@]} -eq 0 ]]; then
    fail "No native library directories found under $libs_root"
  fi
}

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

select_build_abis() {
  local requested="${SIMPLEX_ANDROID_ABIS:-}"
  if [[ -n "$requested" ]]; then
    IFS=',' read -r -a requested_array <<< "$requested"
    local filtered=()
    for abi in "${requested_array[@]}"; do
      abi="${abi// /}"
      if [[ -z "$abi" ]]; then
        continue
      fi
      if printf '%s\n' "${AVAILABLE_ABIS[@]}" | grep -qx "$abi"; then
        filtered+=("$abi")
      else
        warn "Requested ABI '$abi' not available in native libs, skipping"
      fi
    done
    if [[ ${#filtered[@]} -eq 0 ]]; then
      fail "None of the requested ABIs ($requested) are available. Present ABIs: ${AVAILABLE_ABIS[*]}"
    fi
    echo "${filtered[@]}"
    return
  fi

  local host_arch
  host_arch=$(uname -m)
  local preferred=""
  case "$host_arch" in
    x86_64|amd64)
      preferred="x86_64"
      ;;
    arm64|aarch64)
      preferred="arm64-v8a"
      ;;
    *)
      preferred="armeabi-v7a"
      ;;
  esac

  if printf '%s\n' "${AVAILABLE_ABIS[@]}" | grep -qx "$preferred"; then
    echo "$preferred"
    return
  fi

  warn "Host architecture $host_arch has no matching native libs (wanted $preferred). Building with available ABIs: ${AVAILABLE_ABIS[*]}"
  echo "${AVAILABLE_ABIS[@]}"
}

build_apk() {
  local sdk_home="$1"
  shift
  local abis=("$@")
  log "Building SimpleX Chat release APK (ABIs: ${abis[*]})"
  pushd "$MULTIPLATFORM_DIR" >/dev/null
  export ANDROID_HOME="$sdk_home"
  export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"

  local abi_property
  abi_property=$(IFS=,; echo "${abis[*]}")

  ./gradlew clean :android:assembleRelease -PsimplexAbiFilters="$abi_property"
  local built_apk
  built_apk=$(find_apk)
  [[ -n "$built_apk" ]] || fail "Gradle build finished but no release APK was found"
  cp "$built_apk" "$APK_UNSIGNED"
  popd >/dev/null
  log "Unsigned APK copied to $APK_UNSIGNED"
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
  ensure_native_libs
  local abis_output
  abis_output=$(select_build_abis)
  BUILD_ABIS=($abis_output)
  [[ ${#BUILD_ABIS[@]} -gt 0 ]] || fail "No ABIs selected for build"
  local sdk_home
  sdk_home=$(android_home)
  build_apk "$sdk_home" "${BUILD_ABIS[@]}"
  sign_apk "$sdk_home"
  log "Build complete"
}

main "$@"
