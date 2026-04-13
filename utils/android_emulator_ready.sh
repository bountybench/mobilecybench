#!/usr/bin/env bash
set -euo pipefail

# ------------ Configurable timeouts (seconds) ------------
TIMEOUT_CORE="${TIMEOUT_CORE:-30}"   # core service responsiveness; provisioning can lag on cold boots
TIMEOUT_UIA="${TIMEOUT_UIA:-15}"     # uiautomator readiness
TIMEOUT_FOCUS="${TIMEOUT_FOCUS:-10}"  # resumed activity window
POLL_INTERVAL="${POLL_INTERVAL:-1}"   # interval for polling loops

# ------------ Dependencies ------------
source "$(dirname "${BASH_SOURCE[0]}")/wait.sh"
if command -v timeout >/dev/null 2>&1; then
  TIMEOUT_BIN=timeout
elif command -v gtimeout >/dev/null 2>&1; then
  TIMEOUT_BIN=gtimeout
else
  echo "ERROR: missing 'timeout'. On macOS: brew install coreutils" >&2
  exit 1
fi

# ------------ Timing helper ------------
SCRIPT_START=$SECONDS
time_step() {
  local name="$1"; shift
  echo "==> Starting $name" >&2
  local t0=$SECONDS
  "$@"
  local status=$?
  local dt=$((SECONDS - t0))
  echo "<== $name finished in ${dt}s" >&2
  return $status
}

# ------------ Readiness gates ------------

# Probes core services by testing responsiveness of various services
wait_core_services() {
  echo "Waiting for core services (PM/AM/settings)..." >&2

  echo "Waiting for device to be provisioned..." >&2
  "$TIMEOUT_BIN" "$TIMEOUT_CORE" bash -c '
    until adb shell settings get global device_provisioned 2>/dev/null | tr -d "\r" | grep -q "^1$"; do sleep '"$POLL_INTERVAL"'; done
  '

  echo "Waiting for packages to be listed..." >&2
  "$TIMEOUT_BIN" "$TIMEOUT_CORE" bash -c '
    until adb shell cmd package list packages >/dev/null 2>&1; do sleep '"$POLL_INTERVAL"'; done
  '

  echo "Waiting for packages to be installed..." >&2
  "$TIMEOUT_BIN" "$TIMEOUT_CORE" bash -c '
    until adb shell pm list packages -f >/dev/null 2>&1; do sleep '"$POLL_INTERVAL"'; done
  '

  echo "Waiting for activity config to be ready..." >&2
  "$TIMEOUT_BIN" "$TIMEOUT_CORE" bash -c '
    until adb shell cmd activity get-config >/dev/null 2>&1; do sleep '"$POLL_INTERVAL"'; done
  '
}

# Performs actions to stabilize the UI and waits for a resumed activity to confirm responsiveness.
stabilize_ui() {
  echo "Stabilizing UI (wake, unlock, keep awake, go HOME)..." >&2
  adb shell "input keyevent KEYCODE_WAKEUP" 2>/dev/null || true
  adb shell "wm dismiss-keyguard" 2>/dev/null || true
  adb shell "settings put system screen_off_timeout 1800000" 2>/dev/null || true
  adb shell "svc power stayon true" 2>/dev/null || true
  adb shell "input keyevent KEYCODE_HOME" 2>/dev/null || true

  # The output of `dumpsys` is not a stable API and can change.
  # We check for both mResumedActivity (older) and topResumedActivity (newer) for compatibility.
  echo "Waiting for a resumed foreground activity..." >&2
  "$TIMEOUT_BIN" "$TIMEOUT_FOCUS" sh -c '
    until adb shell dumpsys activity activities | grep -E "mResumedActivity|topResumedActivity" >/dev/null; do
      sleep '"$POLL_INTERVAL"';
    done
  '
}

# Waits for the UiAutomator service to be ready to accept commands.
ensure_uiautomator_ready() {
  echo "Pre-flight: quick PM/Activity poke before UiAutomator..." >&2
  adb shell "cmd package resolve-activity android.intent.action.MAIN >/dev/null 2>&1" 2>/dev/null || true

  echo "Probing UiAutomator (with UI nudges)..." >&2
  local start=$SECONDS
  local attempt=0
  while true; do
    if adb shell uiautomator dump >/dev/null 2>&1; then
      echo "UiAutomator dump succeeded." >&2
      return 0
    fi
    attempt=$((attempt+1))
    if (( SECONDS - start >= TIMEOUT_UIA )); then
      echo "Timeout: UiAutomator did not stabilize." >&2
      return 1
    fi
    stabilize_ui
    sleep "$POLL_INTERVAL"
  done
}

main() {
  echo "=== Running android_emulator_ready.sh ===" >&2
  local t0=$SECONDS

  time_step "1) Boot sequence" wait_for_device_boot
  time_step "2) Wait for core services" wait_core_services
  time_step "3) Stabilize UI" stabilize_ui
  time_step "4) UiAutomator readiness" ensure_uiautomator_ready
  time_step "5) Wait for core services post-stabilize" wait_core_services

  local total_dt=$((SECONDS - t0))
  echo "Device is READY for UI tests. Total time: ${total_dt}s" >&2
  echo "=== android_emulator_ready.sh completed in ${total_dt}s ===" >&2
}

main "$@"
