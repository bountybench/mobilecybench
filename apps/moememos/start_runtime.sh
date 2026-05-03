#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "moememos" "$@")
cd "$SCRIPT_DIR"

HEALTH_TIMEOUT=${HEALTH_TIMEOUT:-180}

TARGET_PACKAGE="me.mudkip.moememos"
MEMOS_URL="http://localhost:5230"

start_stack() {
  log_info "Resetting memos-server (clean state)"
  docker compose down -v 2>/dev/null || true
  docker compose up -d --remove-orphans
}

wait_for_health() {
  log_info "Waiting for memos-server to be ready (timeout ${HEALTH_TIMEOUT}s)"
  local start; start=$(date +%s)
  while true; do
    if curl -f -s -o /dev/null "$MEMOS_URL" 2>/dev/null; then
      log_info "memos-server is responding"
      break
    fi
    local now; now=$(date +%s)
    if (( now - start > HEALTH_TIMEOUT )); then
      fatal "Timed out waiting for memos-server to respond"
    fi
    sleep 5
  done
}

enable_adb_root() {
  log_info "Enabling adb root for MoeMemos app-private hydration"
  wait_for_device_boot 120 || fatal "Device not ready for adb root"

  local root_output
  if ! root_output=$(adb root 2>&1); then
    fatal "adb root is required for MoeMemos hydration but failed: $root_output"
  fi
  adb wait-for-device
  wait_for_device_boot 120 || fatal "Device not ready after adb root"

  local adb_uid
  adb_uid=$(adb shell id 2>/dev/null | tr -d '\r' || true)
  if [[ "$adb_uid" != uid=0* ]]; then
    fatal "adb root is required for MoeMemos hydration; current adb shell identity: ${adb_uid:-unknown}"
  fi
}

wait_for_adb_shell_ready() {
  local timeout="${1:-60}"
  local start
  start=$(date +%s)

  log_info "Waiting for adb shell readiness (timeout ${timeout}s)"
  while true; do
    adb wait-for-device >/dev/null 2>&1 || true

    local boot_state
    boot_state="$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r\n' || true)"
    if [[ "$boot_state" == "1" ]] && adb shell id >/dev/null 2>&1; then
      return 0
    fi

    local now
    now=$(date +%s)
    if (( now - start >= timeout )); then
      return 1
    fi
    sleep 1
  done
}

restore_adb_user_shell() {
  log_info "Restoring adb to non-root mode after MoeMemos hydration"
  adb unroot >/dev/null 2>&1 || true
  wait_for_adb_shell_ready 90 || fatal "Device shell not ready after adb unroot"

  local adb_uid
  adb_uid=$(adb shell id 2>/dev/null | tr -d '\r' || true)
  if [[ "$adb_uid" == uid=0* ]]; then
    fatal "adb unroot did not restore a non-root shell; current adb shell identity: ${adb_uid:-unknown}"
  fi
}

install_app() {
  log_info "Installing MoeMemos"
  adb uninstall "$TARGET_PACKAGE" >/dev/null 2>&1 || true
  adb_install_apk "$APK_PATH"
}

run_hydration() {
  log_info "Hydrating MoeMemos benchmark state"
  "$SCRIPT_DIR/scripts/hydration/run_all.sh"
}

main() {
  log_info "Starting MoeMemos setup"
  start_stack
  wait_for_health
  enable_adb_root
  install_app
  run_hydration
  restore_adb_user_shell
  log_info "MoeMemos setup complete! Server: $MEMOS_URL"
}

main "$@"
