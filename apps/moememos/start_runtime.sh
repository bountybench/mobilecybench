#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "moememos" "$@")
cd "$SCRIPT_DIR"

HEALTH_TIMEOUT=${HEALTH_TIMEOUT:-180}

TARGET_PACKAGE="me.mudkip.moememos"
MEMOS_URL="http://localhost:5230"

start_stack() {
  log_info "Starting memos-server"
  docker compose up -d --remove-orphans
}

wait_for_health() {
  log_info "Waiting for memos-server to be ready (timeout ${HEALTH_TIMEOUT}s)"
  local start; start=$(date +%s)
  while true; do
    if curl -f -s -o /dev/null "$MEMOS_URL" 2>/dev/null; then
      log_info "memos-server is responding"
      break
    fi
    local now; now=$(date +%s)
    if (( now - start > HEALTH_TIMEOUT )); then
      fatal "Timed out waiting for memos-server to respond"
    fi
    sleep 5
  done
}

install_app() {
  log_info "Installing MoeMemos"
  adb uninstall "$TARGET_PACKAGE" >/dev/null 2>&1 || true
  adb_install_apk "$APK_PATH"
}

configure_exploit_host_ip() {
  log_info "Configuring exploit scripts with host IP"

  local host_ip
  host_ip=$(ifconfig | grep "inet " | grep -v 127.0.0.1 | awk '{print $2}' | head -1)

  if [[ -z "$host_ip" ]]; then
    log_warn "Could not detect host IP, exploit may not work"
    return
  fi

  log_info "Detected host IP: $host_ip"

  local exploit_script="${SCRIPT_DIR}/synthetic_vulnerabilities/vuln_0/exploit_files/exploit.sh"
  if [[ -f "$exploit_script" ]]; then
    sed -i.bak "s/HOST_IP_PLACEHOLDER/$host_ip/g" "$exploit_script"
    rm -f "${exploit_script}.bak"
    log_info "Updated exploit script with host IP: $host_ip"
  else
    log_warn "Exploit script not found at $exploit_script"
  fi
}

main() {
  log_info "Starting MoeMemos setup"
  start_stack
  wait_for_health
  install_app
  configure_exploit_host_ip
  log_info "MoeMemos setup complete! Server: $MEMOS_URL"
}

main "$@"
