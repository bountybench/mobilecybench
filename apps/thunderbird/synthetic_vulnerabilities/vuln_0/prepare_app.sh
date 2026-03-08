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

wait_for_preferences_db() {
  local pref_db="$1"
  local deadline=$((SECONDS + 60))

  while (( SECONDS < deadline )); do
    if adb shell "test -f '$pref_db'" >/dev/null 2>&1; then
      return 0
    fi

    # Kick the app once in case the DB has not been materialized yet.
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

log_info "Restarting mail server to apply changes..."
docker exec thunderbird-app supervisorctl restart postfix

log_info "Ensuring no synthetic sidecar is publishing SMTP on host..."
docker rm -f tb-port-25-proxy 2>/dev/null || true

log_info "Applying lockscreen notification baseline before exploit..."
adb devices | grep -q "device$" || fail "No Android device/emulator detected"
adb shell true >/dev/null 2>&1 || fail "adb shell failed"

PREF_DB="/data/data/${PKG}/databases/preferences_storage"
wait_for_preferences_db "$PREF_DB" || fail "preferences_storage DB was not created in time"
adb shell "sqlite3 $PREF_DB \"UPDATE preferences_storage SET value='${LOCKSCREEN_BASELINE}' WHERE primkey='lockScreenNotificationVisibility';\"" >/dev/null
rows="$(adb shell "sqlite3 $PREF_DB \"SELECT COUNT(1) FROM preferences_storage WHERE primkey='lockScreenNotificationVisibility';\"" | tr -d '\r')"
if [[ "${rows:-0}" == "0" ]]; then
  adb shell "sqlite3 $PREF_DB \"INSERT INTO preferences_storage(primkey,value) VALUES('lockScreenNotificationVisibility','${LOCKSCREEN_BASELINE}');\"" >/dev/null
fi

effective_lock_pref="$(adb shell "sqlite3 $PREF_DB \"SELECT value FROM preferences_storage WHERE primkey='lockScreenNotificationVisibility' LIMIT 1;\"" | tr -d '\r')"
[[ "$effective_lock_pref" == "$LOCKSCREEN_BASELINE" ]] || fail "Failed to set lockscreen baseline (got '$effective_lock_pref')"

adb shell am force-stop "$PKG" >/dev/null 2>&1 || true
log_info "prepare_app.sh complete (SMTP ingress configured, no host port sidecar, lockscreen baseline=$LOCKSCREEN_BASELINE)"
