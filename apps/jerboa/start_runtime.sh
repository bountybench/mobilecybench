#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "jerboa" "$@")
cd "$SCRIPT_DIR"

SEED_SCRIPT="${SCRIPT_DIR}/jerboa_setup.py"
DEFAULT_OUTPUT="baseline_manifest.json"
SEED_OUTPUT=${SEED_OUTPUT:-$DEFAULT_OUTPUT}

TARGET_PACKAGE="com.jerboa"
TARGET_DIR="/data/data/${TARGET_PACKAGE}"
ANDROID_BASELINE_FILE="${SCRIPT_DIR}/baseline_android_dir.txt"

start_stack(){
  [[ -f "$SCRIPT_DIR/docker-compose.yml" ]] || fatal "docker-compose.yml not found at $SCRIPT_DIR/docker-compose.yml"
  log_info "Starting docker stack"
  docker compose up -d --remove-orphans
}

run_seeder(){
  log_info "Running seeding script -> $SEED_OUTPUT"
  cd "$SCRIPT_DIR"
  SEED_OUTPUT_FILE="$SEED_OUTPUT" python3 "$SEED_SCRIPT" || fatal "Seeding failed"
  [[ -f "$SEED_OUTPUT" ]] || fatal "Expected manifest $SEED_OUTPUT not found"
}

install_app(){
  log_info "Installing Jerboa"
  adb uninstall com.jerboa >/dev/null 2>&1 || true
  adb uninstall com.jerboa.debug >/dev/null 2>&1 || true
  adb_install_apk "$APK_PATH"

  log_info "Launching Jerboa"
  if adb shell pm list packages | grep -q "com.jerboa.debug"; then
    adb shell am start -n com.jerboa.debug/.MainActivity
  else
    adb shell am start -n com.jerboa/.MainActivity
  fi
  sleep 2
}

capture_android_dir_baseline(){
  log_info "Capturing Android directory baseline -> $ANDROID_BASELINE_FILE"
  if adb shell su 0 find "$TARGET_DIR" 2>/dev/null \
    | tr -d '\r' \
    | LC_ALL=C sort -u > "$ANDROID_BASELINE_FILE"; then
    log_info "Wrote $(wc -l < "$ANDROID_BASELINE_FILE") paths to $ANDROID_BASELINE_FILE"
  else
    log_warn "Unable to capture Android baseline"
  fi
}

main(){
  start_stack
  run_seeder
  install_app
  capture_android_dir_baseline
  log_info "Setup complete"
}

main "$@"
