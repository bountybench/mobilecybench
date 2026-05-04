#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"

# Trust our local CA for host-side HTTPS calls (seeder, healthchecks)
export REQUESTS_CA_BUNDLE="$SCRIPT_DIR/../../tls/rootCA.pem"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "owncloud-android" "$@")
cd "$SCRIPT_DIR"

SEED_SCRIPT="${SCRIPT_DIR}/owncloud_setup.py"
DEFAULT_OUTPUT="baseline_manifest.json"
SEED_OUTPUT=${SEED_OUTPUT:-$DEFAULT_OUTPUT}
HEALTH_TIMEOUT=${HEALTH_TIMEOUT:-180}

TARGET_PACKAGE="com.owncloud.android"
TARGET_DIR="/data/data/${TARGET_PACKAGE}"
ANDROID_BASELINE_FILE="${SCRIPT_DIR}/baseline_android_dir.txt"

start_stack(){
  log_info "Starting docker stack"
  docker compose up -d --remove-orphans
}

ensure_oauth2_enabled(){
  log_info "Ensuring oauth2 server app is enabled"
  if docker exec owncloud_server occ app:enable oauth2 >/dev/null 2>&1; then
    log_info "oauth2 app enabled"
  else
    fatal "Failed to enable oauth2 app; check server logs"
  fi
}

wait_for_health(){
  wait_healthy owncloud_server "$HEALTH_TIMEOUT" || fatal "owncloud_server did not become healthy"
}

run_seeder(){
  log_info "Running seeding script -> $SEED_OUTPUT"
  SEED_OUTPUT_FILE="$SEED_OUTPUT" python3 "$SEED_SCRIPT" || fatal "Seeding failed"
  if [[ ! -f "$SEED_OUTPUT" ]]; then
    fatal "Expected manifest $SEED_OUTPUT not found"
  fi
  log_info "Seeder produced $(ls -l "$SEED_OUTPUT" | awk '{print $5" bytes"}')"
}

install_app(){
  log_info "Installing ownCloud on Android device"
  adb uninstall com.owncloud.android >/dev/null 2>&1 || true
  wait_for_device_boot 120 || fatal "Device not ready for APK install"
  adb install -r -g "$APK_PATH"

  log_info "Launching ownCloud..."
  adb shell am start -n com.owncloud.android/com.owncloud.android.ui.activity.SplashActivity >/dev/null 2>&1 || true
  sleep 2
}

capture_android_dir_baseline(){
  log_info "Capturing Android directory baseline -> $ANDROID_BASELINE_FILE"
  adb shell su 0 find "$TARGET_DIR" 2>/dev/null \
    | tr -d '\r' \
    | LC_ALL=C sort -u > "$ANDROID_BASELINE_FILE" || log_warn "Unable to capture Android baseline"
}

summary(){
  log_info "Setup complete"
  log_info "Manifest: $SEED_OUTPUT"
  if [[ -f "$ANDROID_BASELINE_FILE" ]]; then
    log_info "Android baseline: $ANDROID_BASELINE_FILE ($(wc -l < "$ANDROID_BASELINE_FILE") lines)"
  else
    log_warn "Android baseline not found at $ANDROID_BASELINE_FILE. The adb pull may have failed."
  fi
}

main(){
  start_stack
  wait_for_health
  ensure_oauth2_enabled
  run_seeder
  install_app
  capture_android_dir_baseline
  summary
}

main "$@"
