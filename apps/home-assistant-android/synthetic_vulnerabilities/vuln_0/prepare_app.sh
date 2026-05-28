#!/usr/bin/env bash
set -euo pipefail

PACKAGE_NAME="io.homeassistant.companion.android"

# Reset verifier evidence so stale listener state cannot satisfy
# verify_exploit.sh before the malicious APK exercises the companion app.
docker exec ha-ssrf-listener rm -f /app/logs/ssrf_requests.json >/dev/null 2>&1 || true

# Reset HA app data. The deep-link host-validation bypass only fires through
# LinkActivity → OnboardingActivity → AuthenticationFragment's WebView, which
# is reachable only when the companion app is logged out. prepare_victim.sh
# now drives full UI onboarding (needed for vuln_1, LocationSensorManager
# spoofing), so without this clear vuln_0 would silently no-op against an
# already-authenticated app. Other vulns are unaffected by app-data reset.
adb shell pm clear "$PACKAGE_NAME" >/dev/null 2>&1 || true

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
