#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
cd "$SCRIPT_DIR"

ADB_RESTART_ATTEMPTS=${ADB_RESTART_ATTEMPTS:-4}
ADB_RESTART_RETRY_DELAY_SECONDS=${ADB_RESTART_RETRY_DELAY_SECONDS:-5}
TARGET_PACKAGE="me.mudkip.moememos"

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

enable_adb_root() {
  log_info "Enabling adb root for MoeMemos victim hydration"
  wait_for_device_boot 120 || fatal "Device not ready for adb root"

  local attempt root_output root_rc adb_uid
  for ((attempt = 1; attempt <= ADB_RESTART_ATTEMPTS; attempt++)); do
    adb wait-for-device >/dev/null 2>&1 || true

    root_rc=0
    root_output="$(adb root 2>&1)" || root_rc=$?

    adb wait-for-device >/dev/null 2>&1 || true
    wait_for_adb_shell_ready 45 || true

    adb_uid=$(adb shell id 2>/dev/null | tr -d '\r' || true)
    if [[ "$adb_uid" == uid=0* ]]; then
      return 0
    fi

    if (( attempt < ADB_RESTART_ATTEMPTS )); then
      log_warn "adb root attempt ${attempt}/${ADB_RESTART_ATTEMPTS} did not reach root shell; retrying"
      sleep "$ADB_RESTART_RETRY_DELAY_SECONDS"
    fi
  done

  fatal "adb root is required for MoeMemos victim hydration; last rc=${root_rc}, output=${root_output:-<empty>}, identity=${adb_uid:-unknown}"
}

restore_adb_user_shell() {
  log_info "Restoring adb to non-root mode after MoeMemos victim hydration"

  local attempt unroot_output unroot_rc adb_uid
  for ((attempt = 1; attempt <= ADB_RESTART_ATTEMPTS; attempt++)); do
    unroot_rc=0
    unroot_output="$(adb unroot 2>&1)" || unroot_rc=$?

    adb wait-for-device >/dev/null 2>&1 || true
    wait_for_adb_shell_ready 45 || true

    adb_uid=$(adb shell id 2>/dev/null | tr -d '\r' || true)
    if [[ "$adb_uid" != uid=0* && -n "$adb_uid" ]]; then
      return 0
    fi

    if (( attempt < ADB_RESTART_ATTEMPTS )); then
      log_warn "adb unroot attempt ${attempt}/${ADB_RESTART_ATTEMPTS} did not restore user shell; retrying"
      sleep "$ADB_RESTART_RETRY_DELAY_SECONDS"
    fi
  done

  fatal "adb unroot did not restore a non-root shell; last rc=${unroot_rc}, output=${unroot_output:-<empty>}, identity=${adb_uid:-unknown}"
}

ensure_app_installed() {
  if ! adb shell pm list packages | tr -d '\r' | grep -q "^package:${TARGET_PACKAGE}$"; then
    fatal "Package ${TARGET_PACKAGE} is not installed; run start_runtime.sh first"
  fi
}

run_victim_hydration() {
  # Force a victim-account login even if start_runtime.sh configured the app
  # with the non-victim agent account.
  rm -f -- "$SCRIPT_DIR/pipeline/stage3/android_account.json"
  "$SCRIPT_DIR/scripts/hydration/run_victim.sh"
}

main() {
  log_info "Preparing MoeMemos victim state"
  ensure_app_installed
  enable_adb_root
  trap restore_adb_user_shell EXIT
  run_victim_hydration
  trap - EXIT
  restore_adb_user_shell
  log_info "MoeMemos victim state prepared"
}

main "$@"
