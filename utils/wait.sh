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

        # Also wait for package manager to be ready (critical for AOSP)
        log_info "Waiting for package manager service..."
        wait_for_package_manager 30

        return 0
      fi
    fi
    if [ "$(date +%s)" -ge "$end_time" ]; then
      log_error "Timed out waiting for device boot after ${timeout}s."
      return 1
    fi
    printf '.'
    sleep 0.5
  done
}

# Wait for package manager service to be responsive
# This is critical after boot, especially on AOSP images
wait_for_package_manager() {
  local timeout=${1:-30}
  local start_time=$(date +%s)
  local end_time=$((start_time + timeout))

  while true; do
    # Test if package manager can respond to queries
    if adb shell pm path android >/dev/null 2>&1; then
      log_info "Package manager is ready"
      sleep 2  # Additional settling time
      return 0
    fi

    if [ "$(date +%s)" -ge "$end_time" ]; then
      log_error "Timed out waiting for package manager after ${timeout}s."
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
  local output=""
  while true; do
    output=$(bash -c "$cmd" 2>/dev/null || true)
    if printf '%s\n' "$output" | grep -q -Ei "$match"; then
      printf '\n'
      return 0
    fi
    if [ "$(date +%s)" -ge "$end_time" ]; then
      printf '\n' >&2
      printf 'timeout waiting for pattern "%s" from command: %s\n' "$match" "$cmd" >&2
      printf 'last dump:\n%s\n' "$output" >&2
      return 1
    fi
    printf '.'
    sleep 0.5
  done
}

# Wait for UDS to respond to a /status probe. Timeout in seconds.
wait_for_uds_ready() {
  local timeout="${1:-10}"
  local start_ts=$(date +%s)
  while :; do
    if [[ -e "${UDS_PATH}" ]]; then
      # capture curl output to detect "Operation not supported"
      output=$(curl --unix-socket "${UDS_PATH}" --max-time 1 -sS http://localhost/status 2>&1 || true)
      rc=$?
      if [[ $rc -eq 0 && -n "$output" ]]; then
        return 0
      fi
      if echo "$output" | grep -qi 'Operation not supported'; then
        log_warn "UDS unsupported across this host/container filesystem (Operation not supported)."
        return 1
      fi
    fi
    if (( $(date +%s) - start_ts >= timeout )); then
      return 1
    fi
    sleep 0.05
  done
}