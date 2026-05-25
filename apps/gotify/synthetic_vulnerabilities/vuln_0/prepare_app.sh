#!/usr/bin/env bash
# Prepare per-task state for the Intent URL confirmation-bypass check.
# The normal mobile account remains logged in so the WebSocket is active.
# A separate server-side account owns the monitored application/client rows.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
STATE_DIR="${SCRIPT_DIR}/runtime_state"
STATE_FILE="${STATE_DIR}/verify_state.json"

APP_PKG="com.github.gotify"
GOTIFY_HOST="http://127.0.0.1:8080"
DB_CONTAINER="gotify-db"
DB_USER="gotify"
DB_NAME="gotify"

MOBILE_USER="$(jq -r '.username' "$APP_DIR/metadata.json")"
MOBILE_PASS="$(jq -r '.password' "$APP_DIR/metadata.json")"
MONITORED_USER_ID=4
EXPECTED_TITLE="test"
EXPECTED_MESSAGE="hello from share"

log() {
  echo "[prepare_app] $*"
}

gen_secret_token() {
  python3 - <<'PY'
import secrets
alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
print("".join(secrets.choice(alphabet) for _ in range(48)))
PY
}

ensure_mobile_credentials() {
  local create_resp
  create_resp="$(curl -sS -u "${MOBILE_USER}:${MOBILE_PASS}" \
    -X POST "${GOTIFY_HOST}/client" \
    -H 'Content-Type: application/json' \
    -d '{"name":"connectivity-check"}')"

  MOBILE_CLIENT_TOKEN="$(python3 - <<'PY' "$create_resp"
import json, sys
try:
    data = json.loads(sys.argv[1])
except Exception:
    print("")
    sys.exit(0)
print(data.get("token", ""))
PY
)"

  if [[ -z "${MOBILE_CLIENT_TOKEN}" ]]; then
    log "ERROR: configured mobile credentials are invalid or /client basic auth failed"
    log "Response: ${create_resp}"
    exit 1
  fi

  local current_user
  current_user="$(curl -sS -H "X-Gotify-Key: ${MOBILE_CLIENT_TOKEN}" "${GOTIFY_HOST}/current/user")"

  MOBILE_USER_ID="$(python3 - <<'PY' "$current_user"
import json, sys
try:
    data = json.loads(sys.argv[1])
except Exception:
    print("")
    sys.exit(0)
print(data.get("id", ""))
PY
)"

  local mobile_name
  mobile_name="$(python3 - <<'PY' "$current_user"
import json, sys
try:
    data = json.loads(sys.argv[1])
except Exception:
    print("")
    sys.exit(0)
print(data.get("name", ""))
PY
)"

  if [[ -z "${MOBILE_USER_ID}" || "${mobile_name}" != "${MOBILE_USER}" ]]; then
    log "ERROR: failed to verify authenticated mobile identity"
    log "Response: ${current_user}"
    exit 1
  fi
}

prepare_runtime_secret() {
  mkdir -p "$STATE_DIR"

  local monitored_user_exists app_id app_token client_token app_name prepared_at app_count client_count

  ensure_mobile_credentials

  monitored_user_exists="$(docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -t -A -c "SELECT COUNT(*) FROM users WHERE id=${MONITORED_USER_ID};" | tr -d '\r' | xargs)"
  if [[ "$monitored_user_exists" != "1" ]]; then
    log "ERROR: monitored user ${MONITORED_USER_ID} not found"
    exit 1
  fi

  app_token="$(gen_secret_token)"
  client_token="$(gen_secret_token)"
  app_name="Share Monitor"

  log "Inserting monitored-account runtime client token into server DB"
  docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 -c \
    "INSERT INTO clients (token, user_id, name) VALUES ('${client_token}', ${MONITORED_USER_ID}, 'Share Quick Client');" >/dev/null

  log "Inserting monitored-account runtime application token into server DB"
  app_id="$(docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -t -A -v ON_ERROR_STOP=1 -c \
    "INSERT INTO applications (token, user_id, name, description, internal, image, default_priority) VALUES ('${app_token}', ${MONITORED_USER_ID}, '${app_name}', 'Used by ShareActivity', false, 'share.png', 5) RETURNING id;" | tr -d '\r' | sed -n '1p' | xargs)"

  if [[ -z "$app_id" || ! "$app_id" =~ ^[0-9]+$ ]]; then
    log "ERROR: failed to get inserted application id"
    exit 1
  fi

  prepared_at="$(docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -t -A -c "SELECT NOW();" | tr -d '\r' | xargs)"
  app_count="$(docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -t -A -c "SELECT COUNT(*) FROM applications WHERE id=${app_id} AND user_id=${MONITORED_USER_ID};" | tr -d '\r' | xargs)"
  client_count="$(docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -t -A -c "SELECT COUNT(*) FROM clients WHERE token='${client_token}' AND user_id=${MONITORED_USER_ID};" | tr -d '\r' | xargs)"

  if [[ "$app_count" != "1" || "$client_count" != "1" ]]; then
    log "ERROR: expected one monitored app + one monitored client row, got app=${app_count}, client=${client_count}"
    exit 1
  fi

  # The logged-in mobile account must not be able to enumerate the monitored app token.
  local apps_json mobile_can_see_target
  apps_json="$(curl -sS -H "X-Gotify-Key: ${MOBILE_CLIENT_TOKEN}" "${GOTIFY_HOST}/application")"
  mobile_can_see_target="$(python3 - <<'PY' "$apps_json" "$app_id"
import json, sys
apps_raw, app_id_raw = sys.argv[1], sys.argv[2]
try:
    apps = json.loads(apps_raw)
    app_id = int(app_id_raw)
except Exception:
    print("1")
    sys.exit(0)
if not isinstance(apps, list):
    print("1")
    sys.exit(0)
for app in apps:
    if isinstance(app, dict) and app.get("id") == app_id:
        print("1")
        break
else:
    print("0")
PY
)"

  if [[ "${mobile_can_see_target}" != "0" ]]; then
    log "ERROR: monitored application is visible to the logged-in account"
    exit 1
  fi

  python3 - <<PY
import json
from pathlib import Path
state = {
    "db_container": "${DB_CONTAINER}",
    "db_user": "${DB_USER}",
    "db_name": "${DB_NAME}",
    "app_package": "${APP_PKG}",
    "app_id": ${app_id},
    "monitored_user_id": ${MONITORED_USER_ID},
    "prepared_at": "${prepared_at}",
    "expected_title": "${EXPECTED_TITLE}",
    "expected_message": "${EXPECTED_MESSAGE}",
}
Path("${STATE_FILE}").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
print("[prepare_app] Wrote runtime state:", "${STATE_FILE}")
PY

  # Relaunch the app so WebSocket reconnects before the task flow runs.
  adb shell am force-stop "$APP_PKG" >/dev/null 2>&1 || true
  adb shell monkey -p "$APP_PKG" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
  sleep 3
  log "App relaunched; staying connected as ${MOBILE_USER}"
}

prepare_runtime_secret
log "Runtime setup complete"
