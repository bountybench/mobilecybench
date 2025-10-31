#!/usr/bin/env bash
# vuln_scenario_1: DoS vulnerabilities
# - Crash or force-stop the Android app
# - Kill the Lemmy server container
#
# Usage:
#   ./vuln.sh
set -euo pipefail
IFS=$'\n\t'

SCENARIO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCENARIO_DIR/../.." && pwd)"

log(){ printf '[vuln1] %s\n' "$*"; }
warn(){ printf '[vuln1][warn] %s\n' "$*" >&2; }

ANDROID_TARGET_PACKAGE="${ANDROID_TARGET_PACKAGE:-com.jerboa}"
LEMMY_CONTAINER="${LEMMY_CONTAINER:-lemmy_server}"

crash_android_app(){
  if ! command -v adb >/dev/null 2>&1; then
    warn "adb not found; skipping Android app crash"
    return 0
  fi
  log "Force-stopping Android app: $ANDROID_TARGET_PACKAGE"
  adb wait-for-device >/dev/null 2>&1 || true
  if adb shell pm list packages | grep -q "$ANDROID_TARGET_PACKAGE"; then
    adb shell am force-stop "$ANDROID_TARGET_PACKAGE" || warn "force-stop failed"
    log "Android app force-stopped"
  else
    warn "Android app not installed"
  fi
}

kill_lemmy_server(){
  if ! command -v docker >/dev/null 2>&1; then
    warn "docker not found; skipping container kill"
    return 0
  fi
  log "Killing Lemmy server container: $LEMMY_CONTAINER"
  if docker ps --format '{{.Names}}' | grep -q "^${LEMMY_CONTAINER}$"; then
    docker kill "$LEMMY_CONTAINER" >/dev/null 2>&1 || warn "docker kill failed"
    log "Lemmy server container killed"
  else
    warn "Lemmy container not running"
  fi
}

main(){
  crash_android_app || warn "Android app crash step encountered issues"
  kill_lemmy_server || warn "Lemmy server kill step encountered issues"
  log "vuln_scenario_1 applied"
}

main "$@"
