#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"

PACKAGE="$(jq -r '.package_name' "$SCRIPT_DIR/metadata.json")"
USERNAME="$(jq -r '.username' "$SCRIPT_DIR/metadata.json")"
PASSWORD="$(jq -r '.password' "$SCRIPT_DIR/metadata.json")"

log_info "Logging Moodle app in as agent ($USERNAME)..."

for attempt in 1 2 3; do
    wait_adb_ready 120 || log_warn "ADB not ready before Moodle agent login attempt ${attempt}/3"
    adb shell pm clear "$PACKAGE" >/dev/null 2>&1 || true
    sleep 2
    adb shell monkey -p "$PACKAGE" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 || true
    sleep 3

    if python3 "$SCRIPT_DIR/ui_automation/login.py" \
        --username "$USERNAME" \
        --password "$PASSWORD"; then
        log_info "Moodle agent logged in successfully"
        exit 0
    fi

    log_warn "Moodle agent login failed on attempt ${attempt}/3"
    adb kill-server >/dev/null 2>&1 || true
    adb -a start-server >/dev/null 2>&1 || true
    sleep 5
done

fatal "Moodle agent login failed after 3 attempts"
