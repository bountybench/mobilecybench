#!/usr/bin/env bash

set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}" )" && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.yml"
SEED_SCRIPT="${SCRIPT_DIR}/jerboa_setup.py"
DEFAULT_OUTPUT="baseline_manifest.json"
SEED_OUTPUT=${SEED_OUTPUT:-$DEFAULT_OUTPUT}
LOG_PREFIX="[setup]"

TARGET_PACKAGE="com.jerboa"
TARGET_DIR="/data/data/${TARGET_PACKAGE}"
ANDROID_BASELINE_FILE="${SCRIPT_DIR}/baseline_android_dir.txt"

parse_args(){
  if [[ $# -gt 0 ]]; then
    warn "Arguments are no longer supported. Ignoring: $*"
  fi
}

info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*" >&2; }
fail(){ printf '%s[error] %s\n' "$LOG_PREFIX" "$*" >&2; exit 1; }

compose(){
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    docker compose -f "$COMPOSE_FILE" "$@"
  elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose -f "$COMPOSE_FILE" "$@"
  else
    fail "docker compose plugin not available"
  fi
}

start_stack(){
  [[ -f "$COMPOSE_FILE" ]] || fail "docker-compose.yml not found at $COMPOSE_FILE"
  info "Starting docker stack"
  compose up -d --remove-orphans
}

run_seeder(){
  info "Running seeding script -> $SEED_OUTPUT"
  cd "$SCRIPT_DIR"
  SEED_OUTPUT_FILE="$SEED_OUTPUT" python3 "$SEED_SCRIPT" || fail "Seeding failed"
  if [[ ! -f "$SEED_OUTPUT" ]]; then
    fail "Expected manifest $SEED_OUTPUT not found"
  fi
  info "Seeder produced $(ls -l "$SEED_OUTPUT" | awk '{print $5" bytes"}')"
}

install_jerboa(){
  info "Installing Jerboa on Android device from local APK folder"
  adb wait-for-device
  if ! adb get-state >/dev/null 2>&1; then
    fail "No adb device detected; ensure an emulator/device is running"
  fi

  local apk_dir apk
  apk_dir="${SCRIPT_DIR}/apk"
  if [[ ! -d "$apk_dir" ]]; then
    fail "APK folder not found at $apk_dir. Place your jerboa.apk there and re-run."
  fi

  # Pick the newest .apk in the folder (though ideally there should only be one)
  apk=$(ls -1t "$apk_dir"/*.apk 2>/dev/null | head -n 1 || true)
  if [[ -z "$apk" ]]; then
    fail "No .apk found in $apk_dir. Place your jerboa.apk there and re-run."
  fi

  info "Using APK: $(basename "$apk")"

  # Uninstall existing versions
  info "Uninstalling previous packages (if installed)"
  adb uninstall com.jerboa >/dev/null 2>&1 || true
  adb uninstall com.jerboa.debug >/dev/null 2>&1 || true

  info "Installing APK: $apk"

  # Add debugging information for CI troubleshooting
  info "Device info for debugging:"
  info "- SDK level: $(adb shell getprop ro.build.version.sdk 2>/dev/null | tr -d '\r' || echo 'unknown')"
  info "- CPU ABI: $(adb shell getprop ro.product.cpu.abi 2>/dev/null | tr -d '\r' || echo 'unknown')"
  info "- Device model: $(adb shell getprop ro.product.model 2>/dev/null | tr -d '\r' || echo 'unknown')"

  # Check APK info if aapt is available
  if command -v aapt >/dev/null 2>&1; then
    info "APK info: $(aapt dump badging "$apk" 2>/dev/null | grep -E '(package:|native-code:)' | head -2 || echo 'aapt info unavailable')"
  fi

  # Try installation with verbose output for debugging
  info "Attempting installation with detailed error output..."
  local install_output
  if install_output=$(adb install -r "$apk" 2>&1); then
    info "Jerboa installed successfully"
    info "Install output: $install_output"
  else
    fail "Failed to install APK via ADB. Error: $install_output"
  fi
}

launch_jerboa() {
    info "Launching Jerboa..."

    # Launch the app
    if adb shell pm list packages | grep -q "^package:com.jerboa$" && ! adb shell pm list packages | grep -q "com.jerboa.debug"; then
        info "Launching release version"
        adb shell am start -n com.jerboa/.MainActivity
        PACKAGE_NAME="com.jerboa"
    elif adb shell pm list packages | grep -q "com.jerboa.debug"; then
        info "Launching debug version"
        adb shell am start -n com.jerboa.debug/.MainActivity
        PACKAGE_NAME="com.jerboa.debug"
    else
        fail "No Jerboa package found"
    fi

    sleep 1

    # Verify the app is running by checking if the process exists
    if adb shell pidof "$PACKAGE_NAME" >/dev/null 2>&1; then
        info "Jerboa launched successfully (process running)"
    else
        warn "Jerboa may not have launched properly (process not found)."
    fi
}

install_app(){
  install_jerboa
  launch_jerboa
  # Basic verification
  sleep 2
  if adb shell pm list packages | grep -q "com.jerboa"; then
    info "Android app installed (com.jerboa)"
  else
    fail "Android app installation not verified"
  fi
}

capture_android_dir_baseline(){
  info "Capturing Android directory baseline -> $ANDROID_BASELINE_FILE"
  # Ensure a device is connected and ready
  adb wait-for-device >/dev/null 2>&1 || true
  if ! adb get-state >/dev/null 2>&1; then
    warn "No adb device detected; skipping Android baseline capture"
    return 0
  fi
  # Get directory listing
  if adb shell 'command -v su >/dev/null 2>&1' >/dev/null 2>&1; then
    if adb shell su 0 find "$TARGET_DIR" 2>/dev/null \
      | tr -d '\r' \
      | LC_ALL=C sort -u > "$ANDROID_BASELINE_FILE"; then
      info "Wrote $(wc -l < "$ANDROID_BASELINE_FILE") paths to $ANDROID_BASELINE_FILE"
      return 0
    else
      warn "su 0 find failed"
    fi
  fi
  warn "Unable to capture Android baseline"
}

summary(){
  info "Setup complete"
  info "Manifest: $SEED_OUTPUT"
  if [[ -f "$ANDROID_BASELINE_FILE" ]]; then
    info "Android baseline: $ANDROID_BASELINE_FILE ($(wc -l < "$ANDROID_BASELINE_FILE") lines)"
  else
    warn "Android baseline not found at $ANDROID_BASELINE_FILE"
  fi
}

main(){
  parse_args "$@"
  start_stack
  run_seeder
  install_app
  capture_android_dir_baseline
  summary
}

main "$@"
