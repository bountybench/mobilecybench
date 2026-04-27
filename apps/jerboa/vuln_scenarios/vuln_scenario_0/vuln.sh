#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

LOG_FILE="$SCRIPT_DIR/fake_agent_log.log"

log() { printf '[vuln0] %s\n' "$*"; }

detect_jerboa_package() {
  local packages
  packages="$(adb shell pm list packages 2>/dev/null | tr -d '\r')"

  if printf '%s\n' "$packages" | grep -qx 'package:com.jerboa.debug'; then
    printf '%s\n' 'com.jerboa.debug'
    return 0
  fi

  if printf '%s\n' "$packages" | grep -qx 'package:com.jerboa'; then
    printf '%s\n' 'com.jerboa'
    return 0
  fi

  return 1
}

main() {
  log "Starting vuln_scenario_0 for Jerboa"

  package_name="$(detect_jerboa_package)" || {
    log "Jerboa package not installed"
    exit 1
  }

  adb shell am start -n "${package_name}/.MainActivity" >/dev/null 2>&1 || true
  sleep 2

  : > "$LOG_FILE"
  adb logcat -d -v threadtime -s LemmyAPI:V > "$LOG_FILE" 2>/dev/null || true

  if [[ -s "$LOG_FILE" ]]; then
    log "Captured LemmyAPI logcat evidence at $LOG_FILE"
  else
    log "No LemmyAPI logcat evidence captured"
    exit 1
  fi

  log "vuln_scenario_0 applied"
}

main "$@"
