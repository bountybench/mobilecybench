#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
source "$ROOT_DIR/utils/android.sh"

PACKAGE_NAME="$(jq -r '.package_name' "$SCRIPT_DIR/metadata.json")"
APP_USER="$(jq -r '.username' "$SCRIPT_DIR/metadata.json")"
APP_PASS="$(jq -r '.password' "$SCRIPT_DIR/metadata.json")"

if [[ -z "$APP_USER" || "$APP_USER" == "null" || -z "$APP_PASS" || "$APP_PASS" == "null" ]]; then
  fatal "metadata.json must define username/password for Gotify mobile setup"
fi

if [[ "$APP_USER" == "admin" ]]; then
  fatal "Gotify mobile setup must use a non-admin account"
fi

log_info "Preparing Gotify mobile account"
adb shell pm grant "$PACKAGE_NAME" android.permission.POST_NOTIFICATIONS 2>/dev/null || true
adb shell appops set "$PACKAGE_NAME" SCHEDULE_EXACT_ALARM allow 2>/dev/null || true
adb shell appops set "$PACKAGE_NAME" SYSTEM_ALERT_WINDOW allow 2>/dev/null || true
adb shell monkey -p "$PACKAGE_NAME" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 || true
sleep 2

python3 "$SCRIPT_DIR/ui_automation/login.py" --username "$APP_USER" --password "$APP_PASS"
log_info "Gotify mobile account prepared as $APP_USER"
