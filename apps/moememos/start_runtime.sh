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

json_field_from_file() {
  local path="$1"
  local key="$2"
  python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8")).get(sys.argv[2], ""))' "$path" "$key"
}

extract_session_cookie() {
  local headers_file="$1"
  grep -iE "^(Grpc-Metadata-Set-Cookie|Set-Cookie):" "$headers_file" \
    | sed 's/.*user_session=\([^;]*\).*/\1/' \
    | tr -d '\r\n' \
    | tail -1 || true
}

session_cookie_valid() {
  local cookie="$1"
  local http_code
  [[ -n "$cookie" ]] || return 1
  http_code="$(curl -s -o /dev/null -w '%{http_code}' \
    -H "Cookie: user_session=${cookie}" \
    "${MEMOS_URL}/api/v1/auth/sessions/current" || true)"
  [[ "$http_code" == "200" ]]
}

seed_host_user() {
  log_info "Seeding memos HOST user before attacker replay"

  local existing_cookie existing_resource
  if [[ -f "$HOST_STATE_FILE" ]]; then
    existing_cookie="$(json_field_from_file "$HOST_STATE_FILE" host_session_cookie 2>/dev/null || true)"
    existing_resource="$(json_field_from_file "$HOST_STATE_FILE" host_resource 2>/dev/null || true)"
    if [[ -n "$existing_resource" ]] && session_cookie_valid "$existing_cookie"; then
      log_info "Reusing existing HOST session from host seed state"
      chmod 600 "$HOST_STATE_FILE"
      return
    fi
  fi

  local host_user host_pass create_json response http_code body login_json headers_file login_body host_cookie
  host_user="mcbhost"
  host_pass="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
  create_json="$(python3 - <<PYEOF
import json
print(json.dumps({"username": "${host_user}", "password": "${host_pass}"}))
PYEOF
)"

  headers_file="$(mktemp)"

  response="$(curl -s -w '\n%{http_code}' -X POST "${MEMOS_URL}/api/v1/users" \
    -H "Content-Type: application/json" \
    -d "${create_json}")"
  http_code="$(printf '%s\n' "$response" | tail -1)"
  body="$(printf '%s\n' "$response" | sed '$d')"

  if [[ "$http_code" -lt 200 || "$http_code" -ge 300 ]]; then
    fatal "Failed to seed HOST user (HTTP ${http_code}): ${body}"
  fi

  login_json="$(python3 - <<PYEOF
import json
print(json.dumps({"passwordCredentials": {"username": "${host_user}", "password": "${host_pass}"}}))
PYEOF
)"
  login_body="$(curl -s -D "$headers_file" -X POST "${MEMOS_URL}/api/v1/auth/sessions" \
    -H "Content-Type: application/json" \
    -d "$login_json")"
  printf '%s' "$login_body" | grep -q '"user"' || fatal "Failed to login as seeded HOST"
  host_cookie="$(extract_session_cookie "$headers_file")"
  rm -f "$headers_file"
  [[ -n "$host_cookie" ]] || fatal "Failed to extract HOST session cookie"

  python3 - "$HOST_STATE_FILE" "$host_user" "$host_cookie" "$body" <<'PYEOF'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
username = sys.argv[2]
session_cookie = sys.argv[3]
response = json.loads(sys.argv[4])
state = {
    "host_username": username,
    "host_resource": response.get("name", ""),
    "host_session_cookie": session_cookie,
}
path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
path.chmod(0o600)
PYEOF

  log_info "Seeded HOST user '${host_user}', minted a session, and wrote host seed state"
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
