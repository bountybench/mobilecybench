#!/usr/bin/env bash
set -euo pipefail

# ------------ Configurable timeouts (seconds) ------------
TIMEOUT_BOOT="${TIMEOUT_BOOT:-30}"   # full boot + bootanim + compositor + core signals
TIMEOUT_CORE="${TIMEOUT_CORE:-10}"   # core service responsiveness
TIMEOUT_UIA="${TIMEOUT_UIA:-15}"     # uiautomator readiness
TIMEOUT_FOCUS="${TIMEOUT_FOCUS:-10}"  # resumed activity window
NUDGE_SLEEP="${NUDGE_SLEEP:-1}"       # sleep between UI nudges

# ------------ Timing helper ------------
SCRIPT_START=$SECONDS
time_step() {
  local name="$1"; shift
  echo "==> $name"
  local t0=$SECONDS
  "$@"
  local status=$?
  local dt=$((SECONDS - t0))
  echo "<== $name finished in ${dt}s"
  return $status
}

# ------------ Readiness gates ------------

# Waits for the core Android OS to finish its boot sequence.
wait_for_boot() {
  adb wait-for-device

  # Wait for the Android framework to finish booting (including boot animation)
  echo "Waiting for sys.boot_completed=1 and bootanim stopped..."
  timeout "$TIMEOUT_BOOT" sh -c '
    until [ "$(adb shell getprop sys.boot_completed | tr -d "\r")" = "1" ] && \
          [ "$(adb shell getprop init.svc.bootanim | tr -d "\r")" = "stopped" ]; do
      sleep 2;
    done
  '
}

# Restarts the device with root and disables verification, then remounts system partition as read-write
root_and_remount() {
  echo "Requesting root..."
  adb root
  adb wait-for-device

  local sdk
  sdk="$(adb shell "getprop ro.build.version.sdk" 2>/dev/null | tr -d $'\r')"
  echo "Device SDK = ${sdk:-unknown}"

  if [ "${sdk:-0}" -gt 28 ]; then
    echo "Disabling AVB verification (avbctl)..."
    adb shell "avbctl disable-verification"
  else
    echo "Disabling dm-verity..."
    adb disable-verity
  fi

  echo "Rebooting after verification change..."
  adb reboot
  wait_for_boot  # Call wait_for_boot again to ensure the device is fully booted

  echo "Remounting /system (overlayfs expected on API 29+)..."
  adb root
  adb wait-for-device
  adb remount
  adb shell mount | grep -E '(system|vendor|product)'

  echo "Waiting for device to be ready..."
  adb wait-for-device
}

# Probes core services
wait_core_services() {
  echo "Checking WindowManager service..."
  timeout "$TIMEOUT_CORE" sh -c '
    until adb shell service check window | grep -q "found"; do sleep 2; done
  '

  echo "Checking InputManager service..."
  timeout "$TIMEOUT_CORE" sh -c '
    until adb shell service check input | grep -q "found"; do sleep 2; done
  '

  echo "Checking Display service..."
  timeout "$TIMEOUT_CORE" sh -c '
    until adb shell service check display | grep -q "found"; do sleep 2; done
  '

  echo "Probing Activity service..."
  timeout "$TIMEOUT_CORE" sh -c '
    until adb shell service check activity | grep -q "found"; do sleep 2; done
  '

  echo "Probing PackageManager responsiveness..."
  timeout "$TIMEOUT_CORE" sh -c '
    until adb shell cmd package list packages >/dev/null 2>&1; do sleep 2; done
  '

  echo "Probing Settings provider..."
  timeout "$TIMEOUT_CORE" sh -c '
    until adb shell settings list global >/dev/null 2>&1; do sleep 2; done
  '

  echo "Probing Accessibility service..."
  timeout "$TIMEOUT_CORE" sh -c '
    until adb shell service check accessibility | grep -q "found"; do sleep 2; done
  '
}

# Performs actions to stabilize the UI and waits for a resumed activity to confirm responsiveness.
stabilize_ui() {
  echo "Stabilizing UI (wake, unlock, keep awake, go HOME)..."
  adb shell "input keyevent KEYCODE_WAKEUP" 2>/dev/null || true
  adb shell "wm dismiss-keyguard" 2>/dev/null || true
  adb shell "settings put system screen_off_timeout 1800000" 2>/dev/null || true
  adb shell "svc power stayon true" 2>/dev/null || true
  adb shell "input keyevent KEYCODE_HOME" 2>/dev/null || true

  echo "Waiting for a resumed foreground activity..."
  timeout "$TIMEOUT_FOCUS" sh -c '
    until adb shell dumpsys activity activities | grep -E "mResumedActivity|topResumedActivity" >/dev/null; do
      sleep 1;
    done
  '
}

# Waits for the UiAutomator service to be ready to accept commands.
ensure_uiautomator_ready() {
  echo "Pre-flight: quick PM/Activity poke before UiAutomator..."
  adb shell "cmd package resolve-activity android.intent.action.MAIN >/dev/null 2>&1" 2>/dev/null || true

  echo "Probing UiAutomator (with UI nudges)..."
  local start=$SECONDS
  local attempt=0
  while true; do
    if adb shell uiautomator dump >/dev/null 2>&1; then
      echo "UiAutomator dump succeeded."
      return 0
    fi
    attempt=$((attempt+1))
    if (( SECONDS - start >= TIMEOUT_UIA )); then
      echo "Timeout: UiAutomator did not stabilize."
      return 1
    fi
    stabilize_ui
    sleep "$NUDGE_SLEEP"
  done
}

main() {
  echo "=== Running android_emulator_ready.sh ==="
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
    echo "Skipping: 2) Root + disable verification + remount (pass --remount to enable)"
  fi
  time_step "3) Wait for core services" wait_core_services
  time_step "4) Stabilize UI" stabilize_ui
  time_step "5) UiAutomator readiness" ensure_uiautomator_ready
  time_step "6) Wait for core services post-stabilize" wait_core_services

  local total_dt=$((SECONDS - t0))
  echo "Device is READY for UI tests. Total time: ${total_dt}s"
  echo "=== android_emulator_ready.sh completed in ${total_dt}s ==="
}

main "$@"
