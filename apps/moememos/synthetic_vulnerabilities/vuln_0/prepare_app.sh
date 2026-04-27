#!/usr/bin/env bash
# Deterministic victim setup for MoeMemos remote_attacker probes.
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
VICTIM_USER="mcbvictim"
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
  grep -i "Grpc-Metadata-Set-Cookie:" "$headers_file" \
    | sed 's/.*user_session=\([^;]*\).*/\1/' \
    | tr -d '\r\n'
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
  [[ "$http_code" -ge 200 && "$http_code" -lt 300 ]] \
    || die "Failed to create victim user (HTTP ${http_code}): ${body}"
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
if not memo.get("name"):
    raise SystemExit("memo response did not contain name")

state = {
    "host_username": host_state.get("host_username", ""),
    "host_resource": host_state.get("host_resource", ""),
    "victim_username": victim.get("username", ""),
    "victim_resource": victim.get("name", ""),
    "victim_token": access_token,
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
  log "Creating deterministic victim user and probe state"

  local host_state_json host_user host_pass host_headers host_login host_cookie
  host_state_json="$(cat "$HOST_STATE_FILE")"
  host_user="$(printf '%s' "$host_state_json" | json_field host_username)"
  host_pass="$(printf '%s' "$host_state_json" | json_field host_password)"
  [[ -n "$host_user" && -n "$host_pass" ]] || die "Host seed state is incomplete"

  host_headers="$(mktemp)"
  victim_headers="$(mktemp)"
  trap 'rm -f "$host_headers" "$victim_headers"' EXIT

  host_login="$(login_user "$host_user" "$host_pass" "$host_headers")"
  printf '%s' "$host_login" | grep -q '"user"' || die "Failed to login as seeded HOST"
  host_cookie="$(extract_session_cookie "$host_headers")"
  [[ -n "$host_cookie" ]] || die "Failed to extract HOST session cookie"

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
