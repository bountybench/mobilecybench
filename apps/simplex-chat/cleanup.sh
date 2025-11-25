#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_PACKAGE="chat.simplex.app"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.yml"

log(){ printf '[cleanup] %s\n' "$*"; }

compose(){
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    docker compose -f "$COMPOSE_FILE" "$@"
  elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose -f "$COMPOSE_FILE" "$@"
  else
    return 0
  fi
}

log "Removing score artifacts"
rm -f "$SCRIPT_DIR/scores.json" "$SCRIPT_DIR/generic_scores.json"

log "Removing certificates"
rm -rf "$SCRIPT_DIR/certificates"

if command -v adb >/dev/null 2>&1; then
  log "Clearing adb logs"
  adb logcat -c || true
  log "Uninstalling $APP_PACKAGE"
  adb uninstall "$APP_PACKAGE" >/dev/null 2>&1 || true
fi

log "Stopping SimpleX containers"
compose down -v || true

log "Cleanup complete"
