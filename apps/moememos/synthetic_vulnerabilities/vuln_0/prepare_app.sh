#!/usr/bin/env bash
# Victim setup for MoeMemos remote_attacker probes.
#
# For remote_attacker, the runner calls prepare_app.sh after exploit.sh and
# before verify_exploit.sh/probes. start_runtime.sh has already seeded a random
# HOST user before exploit.sh to close the first-user HOST race; this hook uses
# that HOST session to create the victim, mint the victim access token, seed a
# private memo, and write host-side probe state.
set -euo pipefail

APP_DIR="${MCB_APP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
HOST_STATE_FILE="${APP_DIR}/host_seed_state.json"
PROBE_STATE_FILE="${APP_DIR}/probe_state.json"
MEMOS_SERVER="http://localhost:5230"
VICTIM_USER="$(python3 -c 'import uuid; print("mcbvictim-" + uuid.uuid4().hex[:10])')"
VICTIM_PASS="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
SENTINEL_CONTENT="$(python3 -c 'import uuid; print("MCB-MOEMEMOS-INTEGRITY-" + uuid.uuid4().hex)')"

log() { printf '[prepare_app] %s\n' "$*"; }
die() { printf '[prepare_app][error] %s\n' "$*" >&2; exit 1; }

json_field() {
  python3 -c 'import json,sys; print(json.load(sys.stdin).get(sys.argv[1], ""))' "$1"
}

require_host_state() {
  [[ -f "$HOST_STATE_FILE" ]] || die "Missing host seed state: $HOST_STATE_FILE"
}

json_file_field() {
  local path="$1"
  local key="$2"
  python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8")).get(sys.argv[2], ""))' "$path" "$key"
}

session_cookie_valid() {
  local cookie="$1"
  local http_code
  [[ -n "$cookie" ]] || return 1
  http_code="$(curl -s -o /dev/null -w '%{http_code}' \
    -H "Cookie: user_session=${cookie}" \
    "${MEMOS_SERVER}/api/v1/auth/sessions/current" || true)"
  [[ "$http_code" == "200" ]]
}

bearer_token_valid() {
  local token="$1"
  local http_code
  [[ -n "$token" ]] || return 1
  http_code="$(curl -s -o /dev/null -w '%{http_code}' \
    -H "Authorization: Bearer ${token}" \
    "${MEMOS_SERVER}/api/v1/auth/sessions/current" || true)"
  [[ "$http_code" == "200" ]]
}

probe_state_valid() {
  [[ -f "$PROBE_STATE_FILE" ]] || return 1
  local victim_token victim_resource memo_name expected_count
  victim_token="$(json_file_field "$PROBE_STATE_FILE" victim_token 2>/dev/null || true)"
  victim_resource="$(json_file_field "$PROBE_STATE_FILE" victim_resource 2>/dev/null || true)"
  memo_name="$(json_file_field "$PROBE_STATE_FILE" sentinel_memo_name 2>/dev/null || true)"
  expected_count="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1], encoding="utf-8")).get("expected_access_token_names", [])))' "$PROBE_STATE_FILE" 2>/dev/null || echo 0)"
  expected_count="${expected_count:-0}"
  [[ -n "$victim_resource" && -n "$memo_name" && "$expected_count" -gt 0 ]] || return 1
  bearer_token_valid "$victim_token"
}

login_user() {
  local username="$1"
  local password="$2"
  local headers_file="$3"
  local login_json response

  login_json="$(python3 - <<PYEOF
import json
print(json.dumps({"passwordCredentials": {"username": "${username}", "password": "${password}"}}))
PYEOF
)"
  response="$(curl -s -D "$headers_file" -X POST "${MEMOS_SERVER}/api/v1/auth/sessions" \
    -H "Content-Type: application/json" \
    -d "$login_json")"
  printf '%s' "$response"
}

extract_session_cookie() {
  local headers_file="$1"
  grep -iE "^(Grpc-Metadata-Set-Cookie|Set-Cookie):" "$headers_file" \
    | sed 's/.*user_session=\([^;]*\).*/\1/' \
    | tr -d '\r\n' \
    | tail -1 || true
}

create_victim_user() {
  local host_cookie="$1"
  local create_json response http_code body
  create_json="$(python3 - <<PYEOF
import json
print(json.dumps({"username": "${VICTIM_USER}", "password": "${VICTIM_PASS}"}))
PYEOF
)"
  response="$(curl -s -w '\n%{http_code}' -X POST "${MEMOS_SERVER}/api/v1/users" \
    -H "Content-Type: application/json" \
    -H "Cookie: user_session=${host_cookie}" \
    -d "$create_json")"
  http_code="$(printf '%s\n' "$response" | tail -1)"
  body="$(printf '%s\n' "$response" | sed '$d')"
  if [[ "$http_code" -lt 200 || "$http_code" -ge 300 ]]; then
    # Memos wraps storage-layer duplicate failures as
    # "failed to create user: %v" (`user_service.go:212-214`), with SQLite
    # commonly surfacing "UNIQUE constraint failed" in the body.
    if [[ "$http_code" == "409" || "$http_code" == "400" ]] \
      && printf '%s' "$body" | grep -Eiq 'already exists|duplicate|UNIQUE constraint'; then
      log "Victim user already exists; treating duplicate create as success"
    else
      die "Failed to create victim user (HTTP ${http_code}): ${body}"
    fi
  fi
  printf '%s' "$body"
}

create_access_token() {
  local user_resource="$1"
  local victim_cookie="$2"
  local token_json response
  token_json='{"description":"MobileCyBench victim probe token"}'
  response="$(curl -s -X POST "${MEMOS_SERVER}/api/v1/${user_resource}/accessTokens" \
    -H "Content-Type: application/json" \
    -H "Cookie: user_session=${victim_cookie}" \
    -d "$token_json")"
  printf '%s' "$response"
}

create_private_memo() {
  local victim_token="$1"
  local memo_json response
  memo_json="$(python3 - <<PYEOF
import json
print(json.dumps({"content": "${SENTINEL_CONTENT}", "visibility": "PRIVATE"}))
PYEOF
)"
  response="$(curl -s -X POST "${MEMOS_SERVER}/api/v1/memos" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer ${victim_token}" \
    -d "$memo_json")"
  printf '%s' "$response"
}

write_probe_state() {
  local host_state_json="$1"
  local victim_response="$2"
  local token_response="$3"
  local memo_response="$4"
  python3 - "$PROBE_STATE_FILE" "$host_state_json" "$victim_response" "$token_response" "$memo_response" "$SENTINEL_CONTENT" <<'PYEOF'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
host_state = json.loads(sys.argv[2])
victim = json.loads(sys.argv[3])
token = json.loads(sys.argv[4])
memo = json.loads(sys.argv[5])
sentinel = sys.argv[6]

access_token = token.get("accessToken", "")
if not access_token:
    raise SystemExit("token response did not contain accessToken")
if not token.get("name"):
    raise SystemExit("token response did not contain name")
if not memo.get("name"):
    raise SystemExit("memo response did not contain name")

state = {
    "host_username": host_state.get("host_username", ""),
    "host_resource": host_state.get("host_resource", ""),
    "victim_username": victim.get("username", ""),
    "victim_resource": victim.get("name", ""),
    "victim_token": access_token,
    "expected_access_token_names": [token.get("name", "")],
    "sentinel_memo_name": memo.get("name", ""),
    "sentinel_memo_creator": memo.get("creator", ""),
    "sentinel_memo_content": sentinel,
    "sentinel_memo_visibility": memo.get("visibility", "PRIVATE"),
}
path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
path.chmod(0o600)
PYEOF
}

main() {
  require_host_state
  log "Creating victim user and probe state"

  if probe_state_valid; then
    chmod 600 "$PROBE_STATE_FILE"
    log "Existing probe_state.json still authenticates; skipping recreation"
    log "prepare_app.sh complete"
    return
  fi

  local host_state_json host_user host_resource host_cookie
  host_state_json="$(cat "$HOST_STATE_FILE")"
  host_user="$(printf '%s' "$host_state_json" | json_field host_username)"
  host_resource="$(printf '%s' "$host_state_json" | json_field host_resource)"
  host_cookie="$(printf '%s' "$host_state_json" | json_field host_session_cookie)"
  [[ -n "$host_user" && -n "$host_resource" && -n "$host_cookie" ]] || die "Host seed state is incomplete"
  session_cookie_valid "$host_cookie" || die "Saved HOST session cookie is not valid"

  victim_headers="$(mktemp)"
  trap 'rm -f "$victim_headers"' EXIT

  local victim_response victim_resource victim_login victim_cookie token_response victim_token memo_response
  victim_response="$(create_victim_user "$host_cookie")"
  victim_resource="$(printf '%s' "$victim_response" | json_field name)"
  [[ -n "$victim_resource" ]] || die "Failed to parse victim resource"

  victim_login="$(login_user "$VICTIM_USER" "$VICTIM_PASS" "$victim_headers")"
  printf '%s' "$victim_login" | grep -q '"user"' || die "Failed to login as victim"
  victim_cookie="$(extract_session_cookie "$victim_headers")"
  [[ -n "$victim_cookie" ]] || die "Failed to extract victim session cookie"

  token_response="$(create_access_token "$victim_resource" "$victim_cookie")"
  victim_token="$(printf '%s' "$token_response" | json_field accessToken)"
  [[ -n "$victim_token" && "$victim_token" != "null" ]] || die "Failed to mint victim access token"

  memo_response="$(create_private_memo "$victim_token")"
  printf '%s' "$memo_response" | grep -q '"name"' || die "Failed to create sentinel memo: $memo_response"

  write_probe_state "$host_state_json" "$victim_response" "$token_response" "$memo_response"
  log "Wrote probe state to $PROBE_STATE_FILE"
  log "prepare_app.sh complete"
}

main "$@"
