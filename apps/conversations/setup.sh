#!/usr/bin/env bash
# Environment + baseline setup script for Conversations tests.
# Steps:
#   1. Verify prerequisites (adb)
#   2. Build app from source (setup_app_source.sh) - unless --fast is used
#   3. Install Android app on connected device/emulator
#   4. Launch the app
#   5. Verify installation
# Usage:
#   ./setup.sh [--fast] [--help]
#   ./setup.sh --fast        # Skip build, use existing APK
#   FAST=1 ./setup.sh         # Same as --fast
set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}" )" && pwd)"
APP_SOURCE_SCRIPT="${SCRIPT_DIR}/setup_app_source.sh"
CODEBASE_DIR="${SCRIPT_DIR}/codebase"
LOG_PREFIX="[setup]"

TARGET_PACKAGE="eu.siacs.conversations"

# Defaults and CLI flags  
SKIP_BUILD="false"

# Timeout constants
LAUNCH_SLEEP=3

parse_args(){
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --fast|-f)
        SKIP_BUILD="true"
        shift
        ;;
      --help|-h)
        cat <<EOF
Usage: ./setup.sh [--fast] [--help]
  --fast, -f      Skip build, use existing APK
  --help, -h      Show this help

Environment:
  FAST=1          Same as --fast

EOF
        exit 0
        ;;
      *)
        warn "Unknown argument: $1 (ignored)"
        shift
        ;;
    esac
  done
  if [[ "${FAST:-0}" == "1" ]]; then SKIP_BUILD="true"; fi
}

info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*" >&2; }
fail(){ printf '%s[error] %s\n' "$LOG_PREFIX" "$*" >&2; exit 1; }
command_exists(){ command -v "$1" >/dev/null 2>&1; }

ensure_prereqs(){
  info "Checking prerequisites"
  command_exists adb || fail "adb is required"
  info "Prerequisites OK"
}

build_app(){
  if [[ "$SKIP_BUILD" == "true" ]]; then
    info "Skipping build (--fast mode)"
    return 0
  fi
  
  info "Building Conversations from source"
  if [[ ! -x "$APP_SOURCE_SCRIPT" ]]; then
    fail "setup_app_source.sh not found or not executable at $APP_SOURCE_SCRIPT"
  fi
  "$APP_SOURCE_SCRIPT" || fail "App source build failed"
}

get_emulator_arch() {
    # Detect emulator architecture
    if command -v adb >/dev/null 2>&1 && adb get-state >/dev/null 2>&1; then
        local arch
        arch=$(adb shell getprop ro.product.cpu.abi 2>/dev/null | tr -d '\r\n' || echo "")
        if [[ -n "$arch" ]]; then
            info "Detected emulator architecture: $arch"
            echo "$arch"
            return 0
        fi
    fi
    
    # Default to universal if can't detect
    warn "Could not detect emulator architecture, looking for universal APK"
    echo "universal"
}

install_conversations(){
  info "Installing Conversations on Android device"
  adb wait-for-device
  if ! adb get-state >/dev/null 2>&1; then
    fail "No adb device detected; ensure emulator is running"
  fi

  if [[ ! -d "$CODEBASE_DIR" ]]; then
    fail "Codebase not found at $CODEBASE_DIR"
  fi

  local arch
  arch=$(get_emulator_arch)
  
  local apk
  local apk_dir="$CODEBASE_DIR/build/outputs/apk/conversationsFree/release"
  
  # Try architecture-specific signed APK first
  apk=$(find "$apk_dir" -name "*-conversations-free-$arch-release.apk" -not -name "*unsigned*" -type f 2>/dev/null | head -1)
  
  if [[ -z "$apk" ]]; then
    warn "No signed $arch APK found, trying universal APK"
    apk=$(find "$apk_dir" -name "*-conversations-free-universal-release.apk" -not -name "*unsigned*" -type f 2>/dev/null | head -1)
  fi
  
  if [[ -z "$apk" ]]; then
    fail "No signed APK found - run build and signing first"
  fi

  info "Found APK for $arch: $(basename "$apk")"

  # Uninstall existing versions
  info "Uninstalling previous packages (if installed)"
  adb uninstall "$TARGET_PACKAGE" >/dev/null 2>&1 || true

  info "Installing APK: $apk"
  if adb install -r "$apk"; then
    info "Conversations installed successfully"
  else
    fail "Failed to install APK via ADB. Check device connection and APK integrity."
  fi
}

launch_conversations() {
    info "Launching Conversations..."
    
    # Launch the app using the package manager
    if adb shell pm list packages | grep -q "$TARGET_PACKAGE"; then
        info "Launching Conversations"
        # Use monkey to launch the app instead of direct activity launch
        adb shell monkey -p "$TARGET_PACKAGE" -c android.intent.category.LAUNCHER 1
    else
        fail "Conversations package not found"
    fi
    
    sleep $LAUNCH_SLEEP
    
    # Verify the app is running
    if adb shell dumpsys window | grep -q "mCurrentFocus.*$TARGET_PACKAGE"; then
        info "Conversations launched successfully"
    else
        warn "Conversations may not have launched properly (focus not detected)."
    fi
}

install_and_launch_app(){
  if ! command_exists adb; then
    fail "adb not found; cannot install Android app"
  fi
  
  install_conversations
  launch_conversations
}

summary(){
  info "Setup complete"
  info "Conversations is installed and ready for testing"
}

main(){
  parse_args "$@"
  ensure_prereqs
  build_app
  install_and_launch_app
  summary
}

main "$@"