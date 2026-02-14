#!/usr/bin/env bash
set -euo pipefail

# Configure OwnTracks on the emulator as the victim (mqtt_user) by importing
# a config via the owntracks:///config?inline=<base64> intent, then tapping Save.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
source "$APP_DIR/../../utils/android.sh"

# Load victim credentials from secrets.json
SECRETS="$APP_DIR/secrets.json"
[[ -f "$SECRETS" ]] || fatal "secrets.json not found at $SECRETS"
VICTIM_USER=$(jq -r '.admin_username' "$SECRETS")
VICTIM_PASS=$(jq -r '.admin_password' "$SECRETS")
[[ -n "$VICTIM_USER" && -n "$VICTIM_PASS" ]] || fatal "Failed to load victim credentials"
export VICTIM_USER VICTIM_PASS

PKG=$(jq -r '.package_name' "$APP_DIR/metadata.json")

# Build victim config JSON.
INLINE_URI=$(python3 - <<'PY'
import base64
import json
import os
import urllib.parse

config = {
    "_type": "configuration",
    "waypoints": [],
    "host": "10.0.2.2",
    "port": 1883,
    "username": os.environ["VICTIM_USER"],
    "password": os.environ["VICTIM_PASS"],
    "mode": 0,
    "connectionTimeoutSeconds": 30,
    "keepalive": 60,
    "pubTopicBase": "owntracks/%u/%d",
    "subTopic": "owntracks/+/+",
    "tid": "AA",
    "clientId": "owntracks-test-victim",
    "cleanSession": True,
    "tls": False,
    "cmd": True,
    "remoteConfiguration": False,
}

raw = json.dumps(config, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
b64 = base64.b64encode(raw).decode("ascii")
inline = urllib.parse.quote(b64, safe="")
print(f"owntracks:///config?inline={inline}")
PY
)

log_info "Importing victim config (user=$VICTIM_USER) via LoadActivity intent"

adb shell am start -a android.intent.action.VIEW \
    -n "$PKG/.ui.preferences.load.LoadActivity" \
    -d "$INLINE_URI"
sleep 3

log_info "Tapping Save button"
python3 - <<'PY'
import sys, time
import uiautomator2 as u2

d = u2.connect()
btn = d(resourceId="org.owntracks.android:id/save")
if not btn.wait(timeout=5):
    print("[setup_device] ERROR: Save button not found", file=sys.stderr)
    sys.exit(1)
btn.click()
time.sleep(2)
print("[setup_device] Save clicked", file=sys.stderr)
PY

# Start a background MQTT subscriber to capture victim messages.
# The verifier reads this file later — avoids timing issues where the
# response arrives before the verifier starts subscribing.
# The broker doesn't store messages. 
CAPTURE_FILE="/tmp/mqtt_capture.log"

log_info "Starting background MQTT subscriber on owntracks/$VICTIM_USER/#"
docker exec mosquitto sh -c "rm -f $CAPTURE_FILE" 2>/dev/null || true
docker exec -d mosquitto sh -c \
    "mosquitto_sub -h localhost -p 1883 -u '$VICTIM_USER' -P '$VICTIM_PASS' -t 'owntracks/$VICTIM_USER/#' -v > $CAPTURE_FILE 2>&1"

log_info "setup_device.sh complete"
