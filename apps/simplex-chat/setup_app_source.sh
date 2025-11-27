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

ensure_requested_abis_env() {
  if [[ -z "${SIMPLEX_ANDROID_ABIS:-}" ]]; then
    local default_abi
    default_abi=$(default_host_abi)
    export SIMPLEX_ANDROID_ABIS="$default_abi"
    log "SIMPLEX_ANDROID_ABIS not set; defaulting to $default_abi based on host architecture"
  fi
}

parse_requested_abis() {
  ensure_requested_abis_env
  local requested="${SIMPLEX_ANDROID_ABIS:-}"
  IFS=',' read -r -a requested_array <<< "$requested"
  local normalized=()
  for abi in "${requested_array[@]}"; do
    abi="${abi// /}"
    if [[ -n "$abi" ]]; then
      normalized+=("$abi")
    fi
  done
  echo "${normalized[@]}"
}

resolve_path() {
  python3 - "$1" <<'PY'
import os, sys
print(os.path.realpath(sys.argv[1]))
PY
}

ensure_nix() {
  if command -v nix >/dev/null 2>&1; then
    return
  fi

  log "nix not found; installing single-user copy (sudo may be required locally to create /nix)"
  sh <(curl --proto '=https' --tlsv1.2 -L https://nixos.org/nix/install) --no-daemon

  local nix_profile="$HOME/.nix-profile/etc/profile.d/nix.sh"
  [[ -f "$nix_profile" ]] || fail "Nix installation completed but $nix_profile is missing"

  # shellcheck disable=SC1090
  . "$nix_profile"

  command -v nix >/dev/null 2>&1 || fail "Nix installation failed to add 'nix' to PATH"
}

patch_flake_for_x86() {
  local flake="$CODEBASE_DIR/flake.nix"
  [[ -f "$flake" ]] || return
  if grep -q 'pkg-x86_64-android-libsupport' "$flake"; then
    if grep -Eq 'androidX86Pkgs\s*=\s*pkgs\.pkgsCross\.x86_64-android;' "$flake"; then
      return
    fi
  fi
  log "Injecting x86_64 Android hydra jobs into flake.nix"
  python3 - "$flake" <<'PY'
import sys
from pathlib import Path
import re

path = Path(sys.argv[1])
text = path.read_text()

old_binding = "androidX86Pkgs = pkgs.pkgsCross.android64;"
new_binding = "androidX86Pkgs = pkgs.pkgsCross.x86_64-android;"
if old_binding in text and new_binding not in text:
    text = text.replace(old_binding, new_binding, 1)
    path.write_text(text)
    text = path.read_text()

text = text.replace(
    "androidX86Pkgs = pkgs.pkgsCross.android64;",
    "androidX86Pkgs = pkgs.pkgsCross.x86_64-android;",
)

if "pkg-x86_64-android-libsupport" in text:
    raise SystemExit

if "androidX86Pkgs" not in text:
    patterns = [
        r"(android32Pkgs\s*=\s*pkgs\.pkgsCross\.armv7a-android-prebuilt;\s*)",
        r"(androidPkgs\s*=\s*pkgs\.pkgsCross\.aarch64-android;\s*)",
    ]
    insertion = "\n                  androidX86Pkgs = pkgs.pkgsCross.x86_64-android;\n"
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            text = text[:match.end()] + insertion + text[match.end():]
            break
    else:
        raise SystemExit("Unable to locate insertion point for androidX86Pkgs")

def clone(block: str) -> str:
    replacements = [
        ("aarch64-android", "x86_64-android"),
        ("aarch64-unknown-linux-android", "x86_64-unknown-linux-android"),
        ("pkg-aarch64-android", "pkg-x86_64-android"),
        ("androidPkgs", "androidX86Pkgs"),
    ]
    for old, new in replacements:
        block = block.replace(old, new)
    return block

def extract_block(start_token: str, search_from: int) -> tuple[str, int, int]:
    start = text.find(start_token, search_from)
    if start == -1:
        raise SystemExit(f"Unable to locate block start: {start_token.strip()}")
    end_marker = "              });"
    end = text.find(end_marker, start)
    if end == -1:
        raise SystemExit(f"Unable to locate block end for token {start_token.strip()}")
    end += len(end_marker)
    if end < len(text) and text[end] == "\\n":
        end += 1
    return text[start:end], start, end

support_block, _, support_end = extract_block('              "aarch64-android:lib:support" =', 0)
simplex_block, _, simplex_end = extract_block('              "aarch64-android:lib:simplex-chat" =', support_end)

clone_support = clone(support_block)
clone_simplex = clone(simplex_block)

text = text[:support_end] + clone_support + text[support_end:]
simplex_end += len(clone_support)
text = text[:simplex_end] + clone_simplex + text[simplex_end:]
path.write_text(text)
PY

  if ! grep -Eq 'androidX86Pkgs\s*=\s*pkgs\.pkgsCross\.x86_64-android;' "$flake"; then
    fail "Failed to inject androidX86Pkgs binding into flake.nix"
  fi
  if ! grep -q 'pkg-x86_64-android-libsupport' "$flake"; then
    fail "Failed to inject x86_64 hydra jobs into flake.nix"
  fi
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

prepare_native_libs_for_requested_abis() {
  local requested=("$@")
  local processed=""
  for abi in "${requested[@]}"; do
    [[ -n "$abi" ]] || continue
    if [[ " $processed " == *" $abi "* ]]; then
      continue
    fi
    processed+=" $abi"
    case "$abi" in
      x86_64)
	    log "Oops, found x86"
        ;;
      *)
        log "No extra preparation required for ABI '$abi'"
        ;;
    esac
  done
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
  ensure_requested_abis_env
  check_prereqs
  # patch_flake_for_x86
  local requested_abis=($(parse_requested_abis))
  prepare_native_libs_for_requested_abis "${requested_abis[@]}"
  ensure_native_libs
  local build_abis=$(select_build_abis)
  BUILD_ABIS=($build_abis)
  log "Found the following ABIs":
  log $BUILD_ABIS
  [[ ${#BUILD_ABIS[@]} -gt 0 ]] || fail "No ABIs selected for build"
  local sdk_home
  sdk_home=$(android_home)
  build_apk "$sdk_home" "${BUILD_ABIS[@]}"
  sign_apk "$sdk_home"
  log "Build complete"
}

main "$@"
