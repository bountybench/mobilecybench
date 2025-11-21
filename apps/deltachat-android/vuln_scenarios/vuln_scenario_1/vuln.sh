#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOG_PREFIX="[deltachat-vuln1]"
CONTAINER_NAME="${DELTACHAT_CONTAINER_NAME:-deltachat-greenmail}"

log(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*" >&2; }

stop_container(){
  if ! command -v docker >/dev/null 2>&1; then
    warn "docker CLI not available; cannot stop container"
    return 1
  fi

  if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    warn "container ${CONTAINER_NAME} not running before scenario"
    return 0
  fi

  log "stopping container ${CONTAINER_NAME} to simulate DoS"
  if ! docker stop "$CONTAINER_NAME" >/dev/null 2>&1; then
    warn "docker stop failed; attempting docker kill"
    docker kill "$CONTAINER_NAME" >/dev/null 2>&1 || warn "docker kill also failed"
  fi
}

clobber_ports(){
  # Optionally bind to IMAP port to ensure availability probe fails even if container restarts.
  local blocker="$SCRIPT_DIR/port_blocker.pid"
  local python_cmd="import socket, time; s=socket.socket(); s.bind(('0.0.0.0', 1143)); s.listen(); time.sleep(120)"
  if command -v python3 >/dev/null 2>&1; then
    log "binding local IMAP port 1143 to ensure outage"
    nohup python3 -c "$python_cmd" >/dev/null 2>&1 &
    echo $! > "$blocker"
  fi
}

main(){
  log "app dir: $APP_DIR"
  stop_container || warn "failed to stop container"
  clobber_ports || warn "failed to block port"
  log "vulnerability scenario 1 complete"
}

main "$@"
