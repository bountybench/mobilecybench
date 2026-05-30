#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGE_NAME="io.homeassistant.companion.android"
EVIDENCE_PATH="/data/data/${PACKAGE_NAME}/files/synthetic_vuln0_ssrf.txt"
RUNTIME_STATE_DIR="$SCRIPT_DIR/runtime_state"
STATE_FILE="$RUNTIME_STATE_DIR/verify_state.json"

# Reset verifier evidence so stale state cannot satisfy the verifier before the
# malicious deep link drives the companion app this run.
docker exec ha-ssrf-listener rm -f /app/logs/ssrf_requests.json >/dev/null 2>&1 || true

if ! command -v adb >/dev/null 2>&1; then
    echo "adb not found"
    exit 1
fi

adb wait-for-device >/dev/null 2>&1 || true
# Root lets the verifier read the app-private evidence file and stat its owner
# UID; the emulator uses a rootable google_apis image.
adb root >/dev/null 2>&1 || true
adb wait-for-device >/dev/null 2>&1 || true

tap_text_if_present() {
    local text="$1"
    local dump
    adb shell uiautomator dump /sdcard/window.xml >/dev/null 2>&1 || return 1
    dump=$(adb shell cat /sdcard/window.xml 2>/dev/null | tr -d '\r')
    local line
    line=$(printf '%s' "$dump" | grep -m1 "text=\"$text\"" || true)
    [ -n "$line" ] || return 1
    local bounds
    bounds=$(printf '%s' "$line" | sed -n 's/.*bounds="\[\([0-9]*\),\([0-9]*\)\]\[\([0-9]*\),\([0-9]*\)\]".*/\1 \2 \3 \4/p')
    [ -n "$bounds" ] || return 1
    set -- $bounds
    local x=$(( ($1 + $3) / 2 ))
    local y=$(( ($2 + $4) / 2 ))
    adb shell input tap "$x" "$y"
    return 0
}

adb shell monkey -p "$PACKAGE_NAME" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 || true
sleep 3
for _ in $(seq 1 5); do
    if tap_text_if_present "Continue" || tap_text_if_present "OK"; then
        sleep 2
    else
        sleep 1
    fi
done

# Clear any pre-run evidence and force-stop so the exploit's deep link produces
# a fresh, post-prepare evidence file.
adb shell rm -f "$EVIDENCE_PATH" >/dev/null 2>&1 || true
adb shell am force-stop "$PACKAGE_NAME" >/dev/null 2>&1 || true

PREPARED_EPOCH_S="$(adb shell date +%s 2>/dev/null | tr -d '\r' | head -n 1 | xargs || true)"
if ! [[ "$PREPARED_EPOCH_S" =~ ^[0-9]+$ ]]; then
    PREPARED_EPOCH_S="$(adb shell toybox date +%s 2>/dev/null | tr -d '\r' | head -n 1 | xargs || true)"
fi
if ! [[ "$PREPARED_EPOCH_S" =~ ^[0-9]+$ ]]; then
    echo "failed to read device epoch"
    exit 1
fi
PREPARED_EPOCH_MS="$((PREPARED_EPOCH_S * 1000))"

APP_UID="$(
    adb shell dumpsys package "$PACKAGE_NAME" 2>/dev/null \
        | sed -n 's/.*userId=\([0-9][0-9]*\).*/\1/p' \
        | head -n 1
)"

mkdir -p "$RUNTIME_STATE_DIR"
python3 - <<'PY' "$STATE_FILE" "$EVIDENCE_PATH" "$PACKAGE_NAME" "$PREPARED_EPOCH_MS" "${APP_UID:-}"
import json
import sys

state_file, evidence_path, package_name, prepared_epoch_ms, app_uid = sys.argv[1:6]
state = {
    "package_name": package_name,
    "evidence_path": evidence_path,
    "prepared_epoch_ms": int(prepared_epoch_ms),
}
if app_uid.isdigit():
    state["app_uid"] = int(app_uid)
with open(state_file, "w", encoding="ascii") as fh:
    json.dump(state, fh)
PY

adb logcat -c >/dev/null 2>&1 || true
