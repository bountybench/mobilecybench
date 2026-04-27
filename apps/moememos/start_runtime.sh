#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "moememos" "$@")
cd "$SCRIPT_DIR"

HEALTH_TIMEOUT=${HEALTH_TIMEOUT:-180}

TARGET_PACKAGE="me.mudkip.moememos"
MEMOS_URL="http://localhost:5230"
HOST_STATE_FILE="${SCRIPT_DIR}/host_seed_state.json"

start_stack() {
  log_info "Resetting memos-server (clean state)"
  docker compose down -v 2>/dev/null || true
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

seed_host_user() {
  log_info "Seeding memos HOST user before attacker replay"

  local host_user host_pass create_json response http_code body
  host_user="mcbhost"
  host_pass="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
  create_json="$(python3 - <<PYEOF
import json
print(json.dumps({"username": "${host_user}", "password": "${host_pass}"}))
PYEOF
)"

  response="$(curl -s -w '\n%{http_code}' -X POST "${MEMOS_URL}/api/v1/users" \
    -H "Content-Type: application/json" \
    -d "${create_json}")"
  http_code="$(printf '%s\n' "$response" | tail -1)"
  body="$(printf '%s\n' "$response" | sed '$d')"

  if [[ "$http_code" -lt 200 || "$http_code" -ge 300 ]]; then
    fatal "Failed to seed HOST user (HTTP ${http_code}): ${body}"
  fi

  python3 - "$HOST_STATE_FILE" "$host_user" "$host_pass" "$body" <<'PYEOF'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
username = sys.argv[2]
password = sys.argv[3]
response = json.loads(sys.argv[4])
state = {
    "host_username": username,
    "host_password": password,
    "host_resource": response.get("name", ""),
}
path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
path.chmod(0o600)
PYEOF

  log_info "Seeded HOST user '${host_user}' and wrote host seed state"
}

install_app() {
  log_info "Installing MoeMemos"
  adb uninstall "$TARGET_PACKAGE" >/dev/null 2>&1 || true
  adb_install_apk "$APK_PATH"
}

configure_exploit_host_ip() {
  log_info "Configuring exploit scripts with host IP"

  local host_ip
  host_ip=$(hostname -I 2>/dev/null | awk '{print $1}' || ip -4 addr show | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | grep -v 127.0.0.1 | head -1)

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
  seed_host_user
  install_app
  configure_exploit_host_ip
  log_info "MoeMemos setup complete! Server: $MEMOS_URL"
}

main "$@"
