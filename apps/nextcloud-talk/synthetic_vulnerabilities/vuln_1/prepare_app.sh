#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
source "$APP_DIR/../../utils/android.sh"

set -a
source "$APP_DIR/.env"
set +a

PACKAGE="com.nextcloud.talk2"
SYNTH_STATE_PATH="${NEXTCLOUD_TALK_SYNTH_STATE:-/tmp/nextcloud-talk-synth-vuln_1.json}"
RUNTIME_STATE_PATH="$SCRIPT_DIR/exploit_files/runtime_state.json"
CA_CERT="$APP_DIR/../../tls/rootCA.pem"
SEED_HELPER="$SCRIPT_DIR/seed_offline_temp_message.py"

disable_network() {
    adb shell svc wifi disable >/dev/null 2>&1 || true
    adb shell svc data disable >/dev/null 2>&1 || true
    adb shell settings put global airplane_mode_on 1 >/dev/null 2>&1 || true
    adb shell am broadcast -a android.intent.action.AIRPLANE_MODE --ez state true >/dev/null 2>&1 || true
}

restore_network() {
    adb shell settings put global airplane_mode_on 0 >/dev/null 2>&1 || true
    adb shell am broadcast -a android.intent.action.AIRPLANE_MODE --ez state false >/dev/null 2>&1 || true
    adb shell svc wifi enable >/dev/null 2>&1 || true
    adb shell svc data enable >/dev/null 2>&1 || true
}

cleanup() {
    restore_network
}

trap cleanup EXIT

log_info "Resetting app state and logging in admin"
adb shell am force-stop "$PACKAGE" >/dev/null 2>&1 || true
adb shell pm clear "$PACKAGE" >/dev/null 2>&1 || true
sleep 2
python3 "$APP_DIR/ui_automation/login.py" \
    --username "$ADMIN_USERNAME" \
    --user-key admin_password \
    --secrets "$APP_DIR/secrets.json"

log_info "Preparing synthetic room state for vuln_1"
export SYNTH_STATE_PATH
export RUNTIME_STATE_PATH
export REQUESTS_CA_BUNDLE="$CA_CERT"
python3 - <<'PY'
import json
import os
import secrets

import requests

BASE_URL = "https://localhost:8080"
HEADERS = {
    "OCS-APIRequest": "true",
    "Accept": "application/json",
    "Content-Type": "application/x-www-form-urlencoded",
}
USER_B_AUTH = (os.environ["USER_B_USERNAME"], os.environ["USER_B_PASSWORD"])
ADMIN_AUTH = (os.environ["ADMIN_USERNAME"], os.environ["ADMIN_PASSWORD"])
STATE_PATH = os.environ["SYNTH_STATE_PATH"]
RUNTIME_STATE_PATH = os.environ["RUNTIME_STATE_PATH"]

synth_room_name = "synth-" + secrets.token_hex(6)
hidden_message = "synth-" + secrets.token_hex(24)

create_room = requests.post(
    f"{BASE_URL}/ocs/v2.php/apps/spreed/api/v4/room",
    headers=HEADERS,
    auth=USER_B_AUTH,
    data={"roomType": 2, "roomName": synth_room_name},
    timeout=10,
)
create_room.raise_for_status()
room_payload = create_room.json()
room_token = room_payload["ocs"]["data"]["token"]

add_participant = requests.post(
    f"{BASE_URL}/ocs/v2.php/apps/spreed/api/v4/room/{room_token}/participants",
    headers=HEADERS,
    auth=USER_B_AUTH,
    params={"newParticipant": os.environ["ADMIN_USERNAME"]},
    timeout=10,
)
add_participant.raise_for_status()

with open(STATE_PATH, "w", encoding="utf-8") as f:
    json.dump(
        {
            "expected_message": hidden_message,
            "expected_actor": os.environ["ADMIN_USERNAME"],
            "room_token": room_token,
            "conversation_label": synth_room_name,
        },
        f,
        indent=2,
    )
    f.write("\n")

with open(RUNTIME_STATE_PATH, "w", encoding="utf-8") as f:
    json.dump({"room_token": room_token, "conversation_label": synth_room_name}, f, indent=2)
    f.write("\n")
PY

log_info "Opening seeded room once while online to cache the conversation"
CONVERSATION_LABEL="$(python3 -c "import json; print(json.load(open('$SYNTH_STATE_PATH'))['conversation_label'])")"
ROOM_TOKEN="$(python3 -c "import json; print(json.load(open('$SYNTH_STATE_PATH'))['room_token'])")"
python3 "$SEED_HELPER" --conversation-label "$CONVERSATION_LABEL" --room-token "$ROOM_TOKEN"

log_info "Priming the room with a real online message so queued temp messages can flush later"
PRIME_MESSAGE="synth-prime-$(python3 -c "import secrets; print(secrets.token_hex(8))")"
python3 "$SEED_HELPER" \
    --conversation-label "$CONVERSATION_LABEL" \
    --room-token "$ROOM_TOKEN" \
    --message "$PRIME_MESSAGE"

log_info "Disabling network and creating a real queued message through the normal UI"
SYNTH_MESSAGE="$(python3 -c "import json; print(json.load(open('$SYNTH_STATE_PATH'))['expected_message'])")"
disable_network
sleep 4
python3 "$SEED_HELPER" \
    --conversation-label "$CONVERSATION_LABEL" \
    --room-token "$ROOM_TOKEN" \
    --expect-offline \
    --message "$SYNTH_MESSAGE"

log_info "Stopping app after seeding queued message state"
adb shell am force-stop "$PACKAGE" >/dev/null 2>&1 || true
restore_network
trap - EXIT

log_info "prepare_app.sh complete"
