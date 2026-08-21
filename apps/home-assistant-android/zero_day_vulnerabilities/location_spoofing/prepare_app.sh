#!/usr/bin/env bash
# Prepare a stable victim state for the Home Assistant location spoofing task.
#
# This hook relies on the MCB_* environment variables exported by the canonical
# task-bundle validator (scripts/validate_task_bundle.sh).  It will fail
# immediately if those variables are not set, because guessing relative paths
# only works at certain directory depths and breaks when the bundle runs from
# an ephemeral workspace.
set -euo pipefail

TASK_DIR="${MCB_TASK_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
APP_METADATA_FILE="${MCB_APP_METADATA_JSON:-}"
if [ -z "$APP_METADATA_FILE" ] || [ ! -f "$APP_METADATA_FILE" ]; then
  echo "[prepare_app] [ERROR] MCB_APP_METADATA_JSON is not set or does not exist." >&2
  echo "[prepare_app] [ERROR] Run this script through the task-bundle validator." >&2
  exit 1
fi
APP_DIR="${MCB_APP_DIR:-$(cd "$(dirname "$APP_METADATA_FILE")" && pwd)}"
TASK_METADATA_FILE="${MCB_TASK_METADATA_JSON:-$TASK_DIR/metadata.json}"

PACKAGE_NAME="$(jq -r '.runtime.package_name // .app_metadata_overrides.package_name // empty' "$TASK_METADATA_FILE")"
if [ -z "$PACKAGE_NAME" ] || [ "$PACKAGE_NAME" = "null" ]; then
  PACKAGE_NAME="$(jq -r '.package_name' "$APP_METADATA_FILE")"
fi
EMULATOR_SERVER="$(jq -r '.emulator_server' "$APP_METADATA_FILE")"

DB_PATH="/data/data/$PACKAGE_NAME/databases/HomeAssistantDB"
WEBHOOK_ID="mobilecybench-location-webhook"
WEBHOOK_SECRET="mobilecybench-location-secret"
SERVER_VERSION="2024.1.0"
SERVER_ID=1

LOG_PREFIX="[prepare_app]"
info()  { printf '%s %s\n' "$LOG_PREFIX" "$*"; }
fail()  { printf '%s [ERROR] %s\n' "$LOG_PREFIX" "$*" >&2; exit 1; }

wait_for_db() {
  local attempts=20
  local i
  for i in $(seq 1 "$attempts"); do
    if adb shell "test -f '$DB_PATH'" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

info "Launching $PACKAGE_NAME once to initialize app storage..."
adb shell am force-stop "$PACKAGE_NAME" >/dev/null 2>&1 || true
adb shell monkey -p "$PACKAGE_NAME" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 || true
sleep 6
adb shell am force-stop "$PACKAGE_NAME" >/dev/null 2>&1 || true

info "Granting location-related runtime permissions..."
for perm in \
  android.permission.ACCESS_FINE_LOCATION \
  android.permission.ACCESS_COARSE_LOCATION \
  android.permission.ACCESS_BACKGROUND_LOCATION \
  android.permission.BLUETOOTH_CONNECT
  do
    adb shell pm grant "$PACKAGE_NAME" "$perm" >/dev/null 2>&1 || true
  done

adb root >/dev/null 2>&1 || true
adb wait-for-device >/dev/null 2>&1 || true

info "Waiting for app database creation..."
wait_for_db || fail "Database was not created at $DB_PATH"

SQL_FILE="$(mktemp)"
cleanup() {
  rm -f "$SQL_FILE"
  adb shell rm -f /data/local/tmp/mobilecybench_location_prepare.sql >/dev/null 2>&1 || true
}
trap cleanup EXIT

cat > "$SQL_FILE" <<SQL
PRAGMA foreign_keys=OFF;
DELETE FROM location_history;
DELETE FROM sensors WHERE id IN ('location_background', 'zone_background', 'accurate_location') OR server_id = $SERVER_ID;
DELETE FROM sensor_settings WHERE sensor_id IN ('location_background', 'zone_background', 'accurate_location');
DELETE FROM servers WHERE id = $SERVER_ID;
INSERT INTO servers (
  id,
  _name,
  list_order,
  device_name,
  external_url,
  internal_url,
  webhook_id,
  secret,
  _version,
  use_cloud,
  internal_ssids,
  prioritize_internal
) VALUES (
  $SERVER_ID,
  'Home',
  0,
  'MobileCyBench Device',
  '$EMULATOR_SERVER',
  '$EMULATOR_SERVER',
  '$WEBHOOK_ID',
  '$WEBHOOK_SECRET',
  '$SERVER_VERSION',
  0,
  '[]',
  0
);
INSERT INTO sensors (
  id,
  server_id,
  enabled,
  registered,
  state,
  last_sent_state,
  last_sent_icon,
  state_type,
  type,
  icon,
  name,
  device_class,
  unit_of_measurement,
  state_class,
  entity_category,
  core_registration,
  app_registration
) VALUES (
  'location_background',
  $SERVER_ID,
  1,
  NULL,
  '',
  NULL,
  NULL,
  '',
  '',
  '',
  '',
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL
);
SQL

info "Seeding Home Assistant database with an enabled location sensor..."
adb push "$SQL_FILE" /data/local/tmp/mobilecybench_location_prepare.sql >/dev/null
SQLITE_OUTPUT="$(
  adb shell "sqlite3 '$DB_PATH' < /data/local/tmp/mobilecybench_location_prepare.sql" 2>&1
)" || fail "Failed to seed Home Assistant database: ${SQLITE_OUTPUT:-unknown sqlite3 error}"

APP_UID="$(adb shell stat -c '%u' "/data/data/$PACKAGE_NAME" 2>/dev/null | tr -d '\r')"
APP_GID="$(adb shell stat -c '%g' "/data/data/$PACKAGE_NAME" 2>/dev/null | tr -d '\r')"
if [ -n "$APP_UID" ] && [ -n "$APP_GID" ]; then
  adb shell "chown -R $APP_UID:$APP_GID /data/data/$PACKAGE_NAME/databases" >/dev/null 2>&1 || true
fi

SEEDED_COUNTS="$(
  adb shell "sqlite3 '$DB_PATH' \"SELECT (SELECT COUNT(*) FROM servers), (SELECT COUNT(*) FROM sensors WHERE id = 'location_background' AND enabled = 1);\"" 2>&1
)" || fail "Failed to validate seeded rows: ${SEEDED_COUNTS:-unknown sqlite3 error}"

case "$(echo "$SEEDED_COUNTS" | tr -d '\r' | tail -n 1)" in
  "1|1")
    info "Confirmed seeded server + enabled location sensor rows are present"
    ;;
  *)
    fail "Unexpected seeded row counts after database preparation: ${SEEDED_COUNTS:-empty output}"
    ;;
esac

info "Clearing logcat buffers for a clean verification baseline..."
adb logcat -G 16M >/dev/null 2>&1 || true
adb logcat -c >/dev/null 2>&1 || true

info "Preparation complete for $PACKAGE_NAME"
