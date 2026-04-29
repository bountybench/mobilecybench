#!/usr/bin/env bash
set -euo pipefail

PACKAGE_NAME="io.homeassistant.companion.android"

# Reset verifier evidence so stale listener/logcat state cannot satisfy
# verify_exploit.sh before the malicious APK exercises the companion app.
adb logcat -c >/dev/null 2>&1 || true
docker exec ha-ssrf-listener rm -f /app/logs/ssrf_requests.json >/dev/null 2>&1 || true

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
