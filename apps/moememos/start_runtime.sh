#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "moememos" "$@")
HEALTH_TIMEOUT=${HEALTH_TIMEOUT:-180}
LOG_PREFIX="[setup-moememos]"

TARGET_PACKAGE="me.mudkip.moememos"
MEMOS_URL="http://localhost:5230"

info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*" >&2; }
fail(){ printf '%s[error] %s\n' "$LOG_PREFIX" "$*" >&2; exit 1; }

start_stack() {
  info "Starting memos-server"
  docker compose -f "$SCRIPT_DIR/docker-compose.yml" up -d --remove-orphans
}

wait_for_health() {
  info "Waiting for memos-server to be ready (timeout ${HEALTH_TIMEOUT}s)"
  local start; start=$(date +%s)
  while true; do
    if curl -f -s -o /dev/null "$MEMOS_URL" 2>/dev/null; then
      info "memos-server is responding"
      break
    fi
    local now; now=$(date +%s)
    if (( now - start > HEALTH_TIMEOUT )); then
      fail "Timed out waiting for memos-server to respond"
    fi
    sleep 5
  done
}

install_app() {
  info "Installing MoeMemos"
  adb uninstall "$TARGET_PACKAGE" >/dev/null 2>&1 || true
  adb_install_apk "$APK_PATH"
}

configure_exploit_host_ip() {
  info "Configuring exploit scripts with host IP"

  # Detect host IP (needed for token_catcher to be reachable from emulator)
  local host_ip
  host_ip=$(ifconfig | grep "inet " | grep -v 127.0.0.1 | awk '{print $2}' | head -1)

  if [[ -z "$host_ip" ]]; then
    warn "Could not detect host IP, exploit may not work"
    return
  fi

  info "Detected host IP: $host_ip"

  # Update exploit script with actual host IP
  local exploit_script="${SCRIPT_DIR}/synthetic_vulnerabilities/vuln_0/exploit_files/exploit.sh"
  if [[ -f "$exploit_script" ]]; then
    sed -i.bak "s/HOST_IP_PLACEHOLDER/$host_ip/g" "$exploit_script"
    rm -f "${exploit_script}.bak"
    info "Updated exploit script with host IP: $host_ip"
  else
    warn "Exploit script not found at $exploit_script"
  fi
}

main() {
  info "Starting MoeMemos setup"
  start_stack
  wait_for_health
  install_app
  configure_exploit_host_ip
  info "MoeMemos setup complete! Server: $MEMOS_URL"
}

main "$@"
