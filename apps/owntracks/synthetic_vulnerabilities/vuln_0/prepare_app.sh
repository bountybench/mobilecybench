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

adb wait-for-device >/dev/null 2>&1 || true
adb shell am start -W -a android.intent.action.VIEW \
    -n "$PKG/.ui.preferences.load.LoadActivity" \
    -d "$INLINE_URI"

log_info "Tapping Save button"
python3 - <<'PY'
import subprocess
import sys
import time

import uiautomator2 as u2

BTN_ID = "org.owntracks.android:id/save"


def log(msg):
    print(f"[prepare_app] {msg}", file=sys.stderr)


def wait_for_device():
    subprocess.run(
        ["adb", "wait-for-device"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(1)


def connect(max_retries=3):
    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            wait_for_device()
            d = u2.connect()
            _ = d.info
            return d
        except Exception as exc:
            last_exc = exc
            log(f"uiautomator2 connect attempt {attempt}/{max_retries} failed: {exc}")
            time.sleep(2)
    raise RuntimeError("Failed to connect to uiautomator2") from last_exc


last_exc = None
for attempt in range(1, 4):
    d = connect()
    btn = d(resourceId=BTN_ID)
    # Wait up to 30s for the LoadActivity to render the Save button.
    if not btn.wait(timeout=30):
        try:
            print(d.dump_hierarchy(), file=sys.stderr)
        except Exception:
            pass
        log("ERROR: Save button not found after 30s")
        sys.exit(1)

    try:
        btn.click()
    except Exception as exc:
        last_exc = exc
        log(f"Save click attempt {attempt}/3 failed: {exc}")
        time.sleep(2)
        continue

    # Give the import a brief moment to settle before the verifier starts.
    if not d(text="Preferences imported").wait(timeout=10):
        log("Preferences imported confirmation not observed; continuing anyway")
    time.sleep(2)
    log("Save clicked")
    sys.exit(0)

log(f"ERROR: Save click failed after 3 attempts: {last_exc}")
sys.exit(1)
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

log_info "prepare_app.sh complete"
