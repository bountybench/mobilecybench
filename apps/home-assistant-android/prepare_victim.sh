#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"

PACKAGE="io.homeassistant.companion.android"
ATTACKER_MODEL="${MCB_ATTACKER_MODEL:-remote_attacker}"

if [ "$ATTACKER_MODEL" != "remote_attacker" ]; then
    log_info "prepare_victim: attacker_model='$ATTACKER_MODEL' is not remote_attacker; skipping"
    exit 0
fi

log_info "prepare_victim: relaunching $PACKAGE after remote_attacker pm clear"

adb shell pm grant "$PACKAGE" android.permission.POST_NOTIFICATIONS >/dev/null 2>&1 || \
    log_warn "POST_NOTIFICATIONS grant skipped"

if ! adb shell monkey -p "$PACKAGE" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1; then
    fatal "Failed to launch $PACKAGE after pm clear"
fi

for _i in $(seq 1 20); do
    if adb shell pidof "$PACKAGE" >/dev/null 2>&1; then
        log_info "prepare_victim: $PACKAGE is running"
        exit 0
    fi
    sleep 1
done

fatal "$PACKAGE did not start after pm clear"
