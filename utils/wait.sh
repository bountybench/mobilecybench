#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

wait_for_device_boot() {
  local timeout=${1:-600}
  local start_time=$(date +%s)
  local end_time=$((start_time + timeout))
  log_info "Waiting up to ${timeout}s for device to appear and finish booting..."
  while true; do
    if ! command -v adb >/dev/null 2>&1; then
      log_warn "adb not found in PATH inside this environment; retrying"
    fi
    local devices=$(adb devices 2>/dev/null || true)
    if echo "$devices" | grep -qE '^[[:alnum:]-]+\s+device$|^emulator-[0-9]+\s+device$'; then
      local device_id=$(echo "$devices" | awk '/device$/ {print $1; exit}')
      adb wait-for-device 2>/dev/null || true
      local boot_val=$(adb -s "${device_id}" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r\n' || true)
      if [[ "${boot_val}" == "1" ]]; then
        echo
        log_info "Device ${device_id} reports boot completed."
        return 0
      fi
    fi
    if [ "$(date +%s)" -ge "$end_time" ]; then
      log_error "Timed out waiting for device boot after ${timeout}s."
      return 1
    fi
    printf '.'
    sleep 1
  done
}

# Waits for a command's output to match a regex pattern.
wait_for_output() {
  local cmd="$1"
  local match="$2"
  local timeout=${3:-30}
  local start_time=$(date +%s)
  local end_time=$((start_time + timeout))
  while true; do
    if bash -c "$cmd" 2>/dev/null | grep -q -E "$match"; then
      printf '\n'
      return 0
    fi
    local current_time=$(date +%s)
    if [ "$current_time" -ge "$end_time" ]; then
      printf '\n' >&2
      printf 'timeout waiting for pattern "%s" from command: %s\n' "$match" "$cmd" >&2
      return 1
    fi
    printf '.'
    sleep 0.5
  done
}