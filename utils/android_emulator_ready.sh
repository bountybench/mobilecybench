#!/usr/bin/env bash
set -euo pipefail

# ------------ Configurable timeouts (seconds) ------------
TIMEOUT_BOOT="${TIMEOUT_BOOT:-360}"   # full boot + bootanim + compositor + core signals
TIMEOUT_CORE="${TIMEOUT_CORE:-150}"   # core service responsiveness
TIMEOUT_UIA="${TIMEOUT_UIA:-150}"     # uiautomator readiness
TIMEOUT_FOCUS="${TIMEOUT_FOCUS:-90}"  # resumed activity window
NUDGE_SLEEP="${NUDGE_SLEEP:-1}"       # sleep between UI nudges

# ------------ Helpers ------------
log() { echo "$*"; }
need() { command -v "$1" >/dev/null 2>&1 || { echo "Missing dependency: $1"; exit 127; }; }
adb_sh() { adb shell "$@" 2>/dev/null; }  # quiet shell helper

# ------------ Readiness gates ------------
wait_for_boot() {
  log "Waiting for device..."
  adb wait-for-device

  log "Waiting for sys.boot_completed=1 and bootanim stopped..."
  timeout "$TIMEOUT_BOOT" sh -c '
    until [ "$(adb shell getprop sys.boot_completed | tr -d "\r")" = "1" ] && \
          [ "$(adb shell getprop init.svc.bootanim | tr -d "\r")" = "stopped" ]; do
      sleep 2
    done
  '

  log "Waiting for system_server PID..."
  timeout "$TIMEOUT_BOOT" sh -c '
    until adb shell pidof system_server >/dev/null 2>&1; do sleep 2; done
  '

  log "Waiting for SurfaceFlinger service..."
  timeout "$TIMEOUT_BOOT" sh -c '
    until adb shell service check SurfaceFlinger | grep -q "found"; do sleep 2; done
  '

  # Display stack sanity (non-fatal if grep fails but good signal when present)
  adb_sh dumpsys display | head -n 60 || true
}

ensure_root_and_disable_verification() {
  log "Requesting root..."
  adb root || true
  adb wait-for-device

  local sdk
  sdk="$(adb_sh getprop ro.build.version.sdk | tr -d $'\r')"
  log "Device SDK = ${sdk:-unknown}"

  if [ "${sdk:-0}" -gt 28 ]; then
    log "Disabling AVB verification (avbctl)..."
    adb_sh avbctl disable-verification || true
  else
    log "Disabling dm-verity..."
    adb disable-verity || true
  fi

  log "Rebooting after verification change..."
  adb reboot
  wait_for_boot
}

remount_system() {
  log "Remounting /system (overlayfs expected on API 29+)..."
  adb root
  adb wait-for-device
  adb remount
  adb shell mount | grep -E '(system|vendor|product)'
}

wait_core_services() {
  # Window / Input / Display / Activity / Package / Settings / Accessibility
  log "Checking WindowManager service..."
  timeout "$TIMEOUT_CORE" sh -c '
    until adb shell service check window | grep -q "found"; do sleep 2; done
  '

  log "Checking InputManager service..."
  timeout "$TIMEOUT_CORE" sh -c '
    until adb shell service check input | grep -q "found"; do sleep 2; done
  '

  log "Checking Display service..."
  timeout "$TIMEOUT_CORE" sh -c '
    until adb shell service check display | grep -q "found"; do sleep 2; done
  '

  log "Probing Activity service..."
  timeout "$TIMEOUT_CORE" sh -c '
    until adb shell service check activity | grep -q "found"; do sleep 2; done
  '

  log "Probing Window service..."
  timeout "$TIMEOUT_CORE" sh -c '
    until adb shell service check window | grep -q "found"; do sleep 2; done
  '

  log "Probing Input service..."
  timeout "$TIMEOUT_CORE" sh -c '
    until adb shell service check input | grep -q "found"; do sleep 2; done
  '

  log "Probing PackageManager responsiveness..."
  timeout "$TIMEOUT_CORE" sh -c '
    until adb shell cmd package list packages >/dev/null 2>&1; do sleep 2; done
  '

  log "Probing Settings provider..."
  timeout "$TIMEOUT_CORE" sh -c '
    until adb shell settings list global >/dev/null 2>&1; do sleep 2; done
  '

  log "Probing Accessibility service..."
  timeout "$TIMEOUT_CORE" sh -c '
    until adb shell service check accessibility | grep -q "found"; do sleep 2; done
  '
}

stabilize_ui() {
  log "Stabilizing UI (wake, unlock, keep awake, go HOME)..."
  adb_sh input keyevent KEYCODE_WAKEUP || true
  adb_sh wm dismiss-keyguard || true
  adb_sh settings put system screen_off_timeout 1800000 || true
  adb_sh settings put global stay_on_while_plugged_in 3 || true
  adb_sh svc power stayon true || true
  adb_sh input keyevent KEYCODE_HOME || true
}

ensure_resumed_activity() {
  log "Waiting for a resumed foreground activity..."
  timeout "$TIMEOUT_FOCUS" sh -c '
    until adb shell dumpsys activity activities | grep -E "mResumedActivity|topResumedActivity" >/dev/null; do
      sleep 1
    done
  '
}

ensure_uiautomator_ready() {
  log "Pre-flight: quick PM/Activity poke before UiAutomator..."
  adb_sh "cmd package resolve-activity android.intent.action.MAIN >/dev/null 2>&1" || true
  adb_sh "service check activity >/dev/null 2>&1" || true

  log "Probing UiAutomator (with UI nudges)..."
  local start=$SECONDS
  local attempt=0
  while true; do
    if adb shell uiautomator dump >/dev/null 2>&1; then
      log "UiAutomator dump succeeded."
      return 0
    fi
    attempt=$((attempt+1))
    if (( SECONDS - start >= TIMEOUT_UIA )); then
      log "Timeout: UiAutomator did not stabilize."
      log "Quick diagnostics:"
      adb shell getprop | grep -E 'sys.boot_completed|init.svc.bootanim' || true
      adb shell pidof system_server || true
      adb shell dumpsys activity top | head -n 120 || true
      adb shell dumpsys accessibility || true
      return 1
    fi
    log "UiAutomator not ready (attempt $attempt) – nudging UI and retrying..."
    adb_sh input keyevent KEYCODE_WAKEUP || true
    adb_sh wm dismiss-keyguard || true
    adb_sh svc power stayon true || true
    adb_sh input keyevent KEYCODE_HOME || true
    sleep "$NUDGE_SLEEP"
  done
}

# ------------ Main ------------
main() {
  echo "=== Running android_emulator_ready.sh ==="

  wait_for_boot
  ensure_root_and_disable_verification
  remount_system
  wait_core_services
  stabilize_ui
  ensure_resumed_activity
  wait_core_services   # brief re-probe after UI changes
  ensure_uiautomator_ready

  log "Device is READY for UI tests."
  echo "=== android_emulator_ready.sh completed ==="
}

main "$@"
