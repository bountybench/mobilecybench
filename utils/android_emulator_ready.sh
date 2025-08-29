#!/usr/bin/env bash
set -euo pipefail

# ------------ Configurable timeouts (seconds) ------------
TIMEOUT_BOOT="${TIMEOUT_BOOT:-30}"   # full boot + bootanim + compositor + core signals
TIMEOUT_CORE="${TIMEOUT_CORE:-10}"   # core service responsiveness
TIMEOUT_UIA="${TIMEOUT_UIA:-15}"     # uiautomator readiness
TIMEOUT_FOCUS="${TIMEOUT_FOCUS:-10}"  # resumed activity window
POLL_INTERVAL="${POLL_INTERVAL:-1}"   # interval for polling loops

# ------------ Dependencies ------------
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
  echo "==> $name" >&2
  local t0=$SECONDS
  "$@"
  local status=$?
  local dt=$((SECONDS - t0))
  echo "<== $name finished in ${dt}s" >&2
  return $status
}

# ------------ Readiness gates ------------

# Waits for the core Android OS to finish its boot sequence.
wait_for_boot() {
  adb wait-for-device

  # Wait for the Android framework to finish booting (including boot animation)
  echo "Waiting for boot_completed/dev.bootcomplete + compositor..." >&2
  "$TIMEOUT_BIN" "$TIMEOUT_BOOT" sh -c '
    until \
      [ "$(adb shell getprop sys.boot_completed | tr -d "\r")" = "1" ] && \
      [ "$(adb shell getprop dev.bootcomplete | tr -d "\r")" = "1" ] && \
      adb shell pidof surfaceflinger >/dev/null 2>&1 && \
      adb shell pidof system_server  >/dev/null 2>&1
    do sleep '"$POLL_INTERVAL"'; done
  '
}

# Restarts the device with root and disables verification, then remounts system partition as read-write
root_and_remount() {
  echo "Requesting root..." >&2
  adb root
  wait_for_boot

  local sdk
  sdk="$(adb shell "getprop ro.build.version.sdk" 2>/dev/null | tr -d $'\r')"
  echo "Device SDK = ${sdk:-unknown}" >&2

  if [ "${sdk:-0}" -gt 28 ]; then
    echo "Disabling AVB verification (avbctl)..." >&2
    adb shell "avbctl disable-verification"
  else
    echo "Disabling dm-verity..." >&2
    adb disable-verity
  fi

  echo "Rebooting after verification change..." >&2
  adb reboot
  wait_for_boot

  echo "Remounting /system (overlayfs expected on API 29+)..." >&2
  adb root
  wait_for_boot
  adb remount
  adb shell mount | grep -E '(system|vendor|product)' >&2

  wait_for_boot
}

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

  local REMOUNT=false
  for arg in "$@"; do
    if [[ "$arg" == "--remount" ]]; then
      REMOUNT=true
      break
    fi
  done

  time_step "1) Boot sequence" wait_for_boot
  if [ "$REMOUNT" = true ]; then
    time_step "2) Root + disable verification + remount" root_and_remount
  else
    echo "Skipping: 2) Root + disable verification + remount (pass --remount to enable)" >&2
  fi
  time_step "3) Wait for core services" wait_core_services
  time_step "4) Stabilize UI" stabilize_ui
  time_step "5) UiAutomator readiness" ensure_uiautomator_ready
  time_step "6) Wait for core services post-stabilize" wait_core_services

  local total_dt=$((SECONDS - t0))
  echo "Device is READY for UI tests. Total time: ${total_dt}s" >&2
  echo "=== android_emulator_ready.sh completed in ${total_dt}s ===" >&2
}

main "$@"
