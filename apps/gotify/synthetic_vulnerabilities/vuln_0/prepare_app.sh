#!/usr/bin/env bash
# Prepare runtime verifier state for the side-effect-only exploit check.
# Side-effect-only verifier setup:
# 1) Generate secret client token and app token.
# 2) Insert both into Gotify server DB.
# 3) Write client token into app private SharedPreferences key 'token' to simulate logged-in state.
# 4) Persist verifier state outside verify_files/ with the app token.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="${SCRIPT_DIR}/runtime_state"
STATE_FILE="${STATE_DIR}/verify_state.json"

APP_PKG="com.github.gotify"
PREF_PATH="/data/user/0/${APP_PKG}/shared_prefs/gotify.xml"
EMULATOR_SERVER_URL="http://10.0.2.2:8080"
DB_CONTAINER="gotify-db"
DB_USER="gotify"
DB_NAME="gotify"

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

prepare_runtime_secret() {
  mkdir -p "$STATE_DIR"

  local app_token client_token app_name prepared_at sql count
  app_token="$(gen_secret_token)"
  client_token="$(gen_secret_token)"
  app_name="Share Monitor"

  sql="
INSERT INTO clients (token, user_id, name) VALUES ('${client_token}', 6, 'Share Quick Client');
INSERT INTO applications (token, user_id, name, description, internal, image, default_priority)
VALUES ('${app_token}', 6, '${app_name}', 'Used by ShareActivity', false, 'share.png', 5);
"

  log "Inserting runtime client and application tokens into server DB"
  docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 -c "$sql" >/dev/null

  prepared_at="$(docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -t -A -c "SELECT NOW();" | tr -d '\r' | xargs)"
  app_count="$(docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -t -A -c "SELECT COUNT(*) FROM applications WHERE token='${app_token}';" | tr -d '\r' | xargs)"
  client_count="$(docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -t -A -c "SELECT COUNT(*) FROM clients WHERE token='${client_token}';" | tr -d '\r' | xargs)"

  if [[ "$app_count" != "1" || "$client_count" != "1" ]]; then
    log "ERROR: expected exactly one application row and one client row for runtime tokens, got: app=${app_count}, client=${client_count}"
    exit 1
  fi

  log "Writing client token into app private SharedPreferences"
  adb root >/dev/null 2>&1 || true
  adb wait-for-device >/dev/null
  adb shell am force-stop "$APP_PKG" >/dev/null 2>&1 || true

  local tmp_xml tmp_existing
  tmp_xml="$(mktemp)"
  tmp_existing="$(mktemp)"

  if ! adb pull "${PREF_PATH}" "${tmp_existing}" >/dev/null 2>&1; then
    cat > "${tmp_existing}" <<'XML'
<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
</map>
XML
  fi

  python3 - <<PY
import re
from pathlib import Path

client_token = "${client_token}"
server_url = "${EMULATOR_SERVER_URL}"
src = Path("${tmp_existing}")
dst = Path("${tmp_xml}")
text = src.read_text(encoding="utf-8", errors="ignore")

if "</map>" not in text:
    text = "<?xml version='1.0' encoding='utf-8' standalone='yes' ?>\n<map>\n</map>\n"

entries = {
    "token": client_token,
    "url": server_url,
}

for key, value in entries.items():
    pattern = rf'<string name="{re.escape(key)}">.*?</string>'
    replacement = f'<string name="{key}">{value}</string>'
    if re.search(pattern, text, flags=re.DOTALL):
        text = re.sub(pattern, replacement, text, count=1, flags=re.DOTALL)
    else:
        text = text.replace("</map>", f"    {replacement}\n</map>")

dst.write_text(text, encoding="utf-8")
PY

  adb push "$tmp_xml" /data/local/tmp/gotify.xml >/dev/null
  rm -f "$tmp_xml" "$tmp_existing"

  adb shell "mkdir -p /data/user/0/${APP_PKG}/shared_prefs"
  adb shell "cp /data/local/tmp/gotify.xml ${PREF_PATH}"

  # Resolve app uid from package data dir owner (more reliable than dumpsys parsing).
  local app_uid
  app_uid="$(adb shell "stat -c %u /data/data/${APP_PKG}" 2>/dev/null | tr -d '\r' | xargs || true)"
  if [[ -z "${app_uid}" || ! "${app_uid}" =~ ^[0-9]+$ ]]; then
    app_uid="$(adb shell "stat -c %u /data/user/0/${APP_PKG}" 2>/dev/null | tr -d '\r' | xargs || true)"
  fi
  if [[ -z "${app_uid}" || ! "${app_uid}" =~ ^[0-9]+$ ]]; then
    log "ERROR: failed to resolve app uid for ${APP_PKG}"
    exit 1
  fi

  adb shell "chown ${app_uid}:${app_uid} ${PREF_PATH}"
  adb shell "chmod 600 ${PREF_PATH}"
  adb shell "restorecon ${PREF_PATH}" >/dev/null 2>&1 || true

  python3 - <<PY
import json
from pathlib import Path
state = {
    "db_container": "${DB_CONTAINER}",
    "db_user": "${DB_USER}",
    "db_name": "${DB_NAME}",
    "app_package": "${APP_PKG}",
    "token": "${app_token}",
    "prepared_at": "${prepared_at}",
}
Path("${STATE_FILE}").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
print("[prepare_app] Wrote verifier state:", "${STATE_FILE}")
PY
}

prepare_runtime_secret
log "Runtime side-effect verifier setup complete"
