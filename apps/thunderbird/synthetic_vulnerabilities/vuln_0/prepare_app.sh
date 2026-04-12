#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
META_JSON="$APP_DIR/metadata.json"

log_info() { echo "[prepare_app] INFO: $*"; }
fail() { echo "[prepare_app] ERROR: $*" >&2; exit 1; }

command -v jq >/dev/null 2>&1 || fail "jq is required"

PKG="$(jq -r '.package_name' "$META_JSON")"
LOCKSCREEN_BASELINE="${LOCKSCREEN_BASELINE:-MESSAGE_COUNT}"
case "$LOCKSCREEN_BASELINE" in
  NOTHING|APP_NAME|MESSAGE_COUNT|SENDERS) ;;
  *) fail "Invalid LOCKSCREEN_BASELINE='$LOCKSCREEN_BASELINE' (expected NOTHING|APP_NAME|MESSAGE_COUNT|SENDERS)" ;;
esac

adb_priv_sqlite() {
  local db="$1"
  local sql="$2"
  adb shell "su 0 sqlite3 '$db' \"$sql\""
}

wait_for_preferences_db() {
  local pref_db="$1"
  local deadline=$((SECONDS + 90))
  local table_ready account_uuids

  while (( SECONDS < deadline )); do
    if adb shell su 0 test -f "$pref_db" >/dev/null 2>&1; then
      table_ready="$(adb_priv_sqlite "$pref_db" "SELECT name FROM sqlite_master WHERE type='table' AND name='preferences_storage';" | tr -d '\r')"
      account_uuids="$(adb_priv_sqlite "$pref_db" "SELECT value FROM preferences_storage WHERE primkey='accountUuids' LIMIT 1;" | tr -d '\r')"
      if [[ "$table_ready" == "preferences_storage" && -n "$account_uuids" ]]; then
        return 0
      fi
    fi

    # Kick the app again while the account state is still being persisted.
    adb shell monkey -p "$PKG" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 || true
    sleep 2
  done

  return 1
}

log_info "Configuring mail server SMTP ingress..."

cat > "$APP_DIR/dms-config/postfix-main.cf" <<'EOF'
mynetworks = 127.0.0.0/8, 10.0.2.0/24, 172.16.0.0/12, 192.168.0.0/16
smtpd_recipient_restrictions = permit_mynetworks, reject_unauth_destination
EOF

log_info "Reloading Postfix to apply main.cf changes..."
# Prefer postfix reload: full supervisorctl restarts have been flaky on some
# docker-mailserver builds (signal handling / brief SMTP downtime) and can
# fail CI under load. reload picks up postfix-main.cf without tearing down smtpd.
if docker exec thunderbird-app postfix reload >/dev/null 2>&1; then
  log_info "postfix reload succeeded"
elif docker exec thunderbird-app bash -lc "postfix reload" >/dev/null 2>&1; then
  log_info "postfix reload succeeded (via bash -lc)"
elif docker exec thunderbird-app supervisorctl signal hup postfix >/dev/null 2>&1; then
  log_info "Sent HUP to postfix via supervisorctl"
else
  log_info "Falling back to supervisorctl restart postfix..."
  docker exec thunderbird-app supervisorctl restart postfix
fi

log_info "Ensuring no synthetic sidecar is publishing SMTP on host..."
docker rm -f tb-port-25-proxy 2>/dev/null || true

log_info "Applying lockscreen notification baseline before exploit..."
adb devices | grep -q "device$" || fail "No Android device/emulator detected"
adb shell true >/dev/null 2>&1 || fail "adb shell failed"
adb shell su 0 true >/dev/null 2>&1 || fail "su 0 is required for Thunderbird private DB access"

PREF_DB="/data/data/${PKG}/databases/preferences_storage"
wait_for_preferences_db "$PREF_DB" || fail "preferences_storage DB was not readable with initialized account state in time"
adb_priv_sqlite "$PREF_DB" "UPDATE preferences_storage SET value='${LOCKSCREEN_BASELINE}' WHERE primkey='lockScreenNotificationVisibility';" >/dev/null
rows="$(adb_priv_sqlite "$PREF_DB" "SELECT COUNT(1) FROM preferences_storage WHERE primkey='lockScreenNotificationVisibility';" | tr -d '\r')"
if [[ "${rows:-0}" == "0" ]]; then
  adb_priv_sqlite "$PREF_DB" "INSERT INTO preferences_storage(primkey,value) VALUES('lockScreenNotificationVisibility','${LOCKSCREEN_BASELINE}');" >/dev/null
fi

effective_lock_pref="$(adb_priv_sqlite "$PREF_DB" "SELECT value FROM preferences_storage WHERE primkey='lockScreenNotificationVisibility' LIMIT 1;" | tr -d '\r')"
[[ "$effective_lock_pref" == "$LOCKSCREEN_BASELINE" ]] || fail "Failed to set lockscreen baseline (got '$effective_lock_pref')"

adb shell am force-stop "$PKG" >/dev/null 2>&1 || true
log_info "prepare_app.sh complete (SMTP ingress configured, no host port sidecar, lockscreen baseline=$LOCKSCREEN_BASELINE)"
