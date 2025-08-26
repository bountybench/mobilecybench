#!/usr/bin/env bash
set -euo pipefail

# Configurable timeouts (seconds)
TIMEOUT_BOOT=${TIMEOUT_BOOT:-180}
TIMEOUT_CORE=${TIMEOUT_CORE:-90}
TIMEOUT_UIA=${TIMEOUT_UIA:-90}
TIMEOUT_FOCUS=${TIMEOUT_FOCUS:-30}

wait_for_boot() {
  adb wait-for-device
  timeout "$TIMEOUT_BOOT" adb shell 'until [ "$(getprop sys.boot_completed)" = "1" ]; do sleep 1; done'
}

ensure_root_and_disable_verification() {
  adb root || true
  adb wait-for-device
  local sdk
  sdk="$(adb shell getprop ro.build.version.sdk | tr -d '\r')"
  echo "Device SDK = ${sdk}"
  if [ "${sdk:-0}" -gt 28 ]; then
    adb shell avbctl disable-verification || true
  else
    adb disable-verity || true
  fi

  adb reboot
  adb wait-for-device
  wait_for_boot
}

remount_system() {
  adb root || true
  adb wait-for-device
  adb remount || true
  adb shell mount | grep -E '(system|vendor|product)' || true
}

wait_core_services() {
  timeout "$TIMEOUT_CORE" adb shell 'until cmd package list packages >/dev/null 2>&1; do sleep 1; done'
  timeout "$TIMEOUT_CORE" adb shell 'until settings list global >/dev/null 2>&1; do sleep 1; done'
  timeout "$TIMEOUT_CORE" adb shell 'until sm list-disks >/dev/null 2>&1; do sleep 1; done'
}

stabilize_ui() {
  adb shell input keyevent 224 || true        # WAKEUP
  adb shell wm dismiss-keyguard || true
  adb shell settings put global stay_on_while_plugged_in 3 || true
  adb shell svc power stayon true || true
  adb shell input keyevent 3 || true          # HOME
}

ensure_resumed_activity() {
  timeout 60 adb shell 'until dumpsys activity activities | grep -E "mResumedActivity|topResumedActivity" >/dev/null; do sleep 1; done'
}

ensure_uiautomator_ready() {
  timeout "$TIMEOUT_UIA" adb shell 'i=0; while [ $i -lt 90 ]; do if uiautomator dump >/dev/null 2>&1; then echo "UiAutomator dump succeeded."; exit 0; fi; echo "UiAutomator dump failed, attempting recovery (attempt #$i)..."; input keyevent 224 || true; wm dismiss-keyguard || true; input keyevent 3 || true; sleep 1; i=$((i+1)); done; echo "Timeout: UiAutomator did not stabilize after multiple recovery attempts." >&2; exit 1'
}

check_focused_window_non_fatal() {
  timeout "$TIMEOUT_FOCUS" adb shell 'until dumpsys window windows | grep -q "mCurrentFocus"; do sleep 1; done' || echo "Warning: No focused window found, but proceeding anyway."
}

main() {
  wait_for_boot
  ensure_root_and_disable_verification
  remount_system
  wait_core_services
  stabilize_ui
  ensure_resumed_activity
  ensure_uiautomator_ready
  check_focused_window_non_fatal
}

main "$@"


