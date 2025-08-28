#!/usr/bin/env bash
set -euo pipefail

# ------------ Configurable timeouts (seconds) ------------
TIMEOUT_BOOT="${TIMEOUT_BOOT:-60}"   # full boot + bootanim + compositor + core signals
TIMEOUT_CORE="${TIMEOUT_CORE:-30}"   # core service responsiveness
TIMEOUT_UIA="${TIMEOUT_UIA:-45}"     # uiautomator readiness
TIMEOUT_FOCUS="${TIMEOUT_FOCUS:-30}"  # resumed activity window
NUDGE_SLEEP="${NUDGE_SLEEP:-1}"       # sleep between UI nudges

# ------------ Readiness gates ------------

# Waits for the core Android OS to finish its boot sequence.
wait_for_boot() {
  adb wait-for-device

  # 1. Wait for the Android framework to finish booting.
  #    - 'sys.boot_completed' is the high-level OS flag.
  #    - 'init.svc.bootanim' ensures the boot animation has stopped.
  echo "Waiting for sys.boot_completed=1 and bootanim stopped..."
  timeout "$TIMEOUT_BOOT" sh -c '
    until [ "$(adb shell getprop sys.boot_completed | tr -d "\r")" = "1" ] && \
          [ "$(adb shell getprop init.svc.bootanim | tr -d "\r")" = "stopped" ]; do
      sleep 2;
    done
  '

  # 2. Wait 'system_server' (hosts most core services)
  echo "Waiting for system_server PID..."
  timeout "$TIMEOUT_BOOT" sh -c '
    until adb shell pidof system_server >/dev/null 2>&1; do
      sleep 2;
    done
  '

  # 3. 'SurfaceFlinger' composits different graphical layers -> checks graphics and UI rendering pipeline are running
  echo "Waiting for SurfaceFlinger service..."
  timeout "$TIMEOUT_BOOT" sh -c '
    until adb shell service check SurfaceFlinger | grep -q "found"; do
      sleep 2;
    done
  '
}

# Restarts the device with root privileges and disables dm-verity/AVB. Expensive.
ensure_root_and_disable_verification() {
  echo "Requesting root..."
  adb root || true
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
  wait_for_boot
}

# Remounts the system partition as read-write. Requires root.
remount_system() {
  echo "Remounting /system (overlayfs expected on API 29+)..."
  adb root || true
  adb wait-for-device
  adb remount || true
  adb shell mount | grep -E '(system|vendor|product)'
}

# Probes critical system services to ensure they are running and responsive.
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
      echo "Quick diagnostics:"
      adb shell getprop | grep -E 'sys.boot_completed|init.svc.bootanim' || true
      adb shell pidof system_server || true
      adb shell dumpsys activity top | head -n 120 || true
      adb shell dumpsys accessibility || true
      return 1
    fi
    stabilize_ui
    sleep "$NUDGE_SLEEP"
  done
}

main() {
  echo "=== Running android_emulator_ready.sh ==="

  # 1. Wait for the Android framework to finish booting.
  wait_for_boot

  # 2. Ensure root and disable verification, then remount the system partition as read-write.
  ensure_root_and_disable_verification
  remount_system
  
  # 3. Wait for core services and UI to be ready.
  wait_core_services
  stabilize_ui
  ensure_uiautomator_ready

  # 4. Confirm core services are still running after UI changes
  wait_core_services

  echo "Device is READY for UI tests."
  echo "=== android_emulator_ready.sh completed ==="
}

main "$@"
