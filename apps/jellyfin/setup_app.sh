#!/bin/bash
set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}" )" && pwd)"
CODEBASE_DIR="${SCRIPT_DIR}/codebase"
LOG_PREFIX="[setup_app]"

TARGET_PACKAGE="org.jellyfin.mobile"

# Timeout constants
LAUNCH_SLEEP=3

info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*" >&2; }
fail(){ printf '%s[error] %s\n' "$LOG_PREFIX" "$*" >&2; exit 1; }
command_exists(){ command -v "$1" >/dev/null 2>&1; }

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

install_jellyfin(){
  info "Installing Jellyfin on Android device"
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
  local apk_dir="$CODEBASE_DIR/app/build/outputs/apk/libre/release"

  # Try architecture-specific signed APK first
  apk=$(find "$apk_dir" -name "*-$arch-release.apk" -not -name "*unsigned*" -type f 2>/dev/null | head -1)

  if [[ -z "$apk" ]]; then
    warn "No signed $arch APK found, trying any signed APK"
    apk=$(find "$apk_dir" -name "*-release.apk" -not -name "*unsigned*" -type f 2>/dev/null | head -1)
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
    info "Jellyfin installed successfully"
  else
    fail "Failed to install APK via ADB. Check device connection and APK integrity."
  fi
}

launch_jellyfin() {
    info "Launching Jellyfin..."

    # Launch the app using the package manager
    if adb shell pm list packages | grep -q "$TARGET_PACKAGE"; then
        info "Launching Jellyfin"
        # Use monkey to launch the app instead of direct activity launch
        adb shell monkey -p "$TARGET_PACKAGE" -c android.intent.category.LAUNCHER 1
    else
        fail "Jellyfin package not found"
    fi

    sleep $LAUNCH_SLEEP

    # Verify the app is running
    if adb shell dumpsys window | grep -q "mCurrentFocus.*$TARGET_PACKAGE"; then
        info "Jellyfin launched successfully"
    else
        warn "Jellyfin may not have launched properly (focus not detected)."
    fi
}

# Main function
main() {
    info "Installing and launching Jellyfin app"

    if ! command_exists adb; then
        fail "adb not found; cannot install Android app"
    fi

    install_jellyfin
    launch_jellyfin

    info "Jellyfin app setup complete"
}

# Run main function
main "$@"