#!/bin/bash
# Seed the OpenHAB environment with realistic smart home data.
# Called by start_runtime.sh after user setup is complete.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Use docker exec to avoid Docker Desktop port-mapping issues on macOS.
# The REST API is always reachable at localhost:8080 from inside the container.
CURL_PREFIX="docker exec openhab curl"
BASE_URL="http://localhost:8080"

# Read admin credentials
source <(python3 -c "
import json
with open('$SCRIPT_DIR/secrets.json') as f:
    s = json.load(f)
print(f'ADMIN_USER={s[\"adminuser_username\"]}')
print(f'ADMIN_PASS={s[\"adminuser_password\"]}')
")

AUTH="$ADMIN_USER:$ADMIN_PASS"

wait_for_rest_api() {
    local max_attempts=90
    for i in $(seq 1 $max_attempts); do
        if $CURL_PREFIX -sf --connect-timeout 5 --max-time 15 -u "$AUTH" "$BASE_URL/rest/items" > /dev/null 2>&1; then
            echo "[INFO]  REST API ready (attempt $i)"
            return 0
        fi
        if [ $((i % 10)) -eq 0 ]; then
            echo "[INFO]  Still waiting for REST API... (attempt $i/$max_attempts)"
        fi
        sleep 2
    done
    echo "[ERROR] REST API not responding after $max_attempts attempts (~$((max_attempts * 2))s)"
    return 1
}

items_already_seeded() {
    local count
    count=$($CURL_PREFIX -sf --connect-timeout 5 --max-time 15 -u "$AUTH" "$BASE_URL/rest/items" 2>/dev/null | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")
    [ "$count" -ge 17 ]
}

create_item() {
    local name="$1" type="$2" label="$3" category="${4:-}" groups="${5:-}"
    local group_json=""
    if [ -n "$groups" ]; then
        group_json="\"groupNames\":[\"$groups\"],"
    fi
    local cat_json=""
    if [ -n "$category" ]; then
        cat_json="\"category\":\"$category\","
    fi
    $CURL_PREFIX -s -X PUT "$BASE_URL/rest/items/$name" -u "$AUTH" \
        -H "Content-Type: application/json" \
        -d "{\"type\":\"$type\",\"name\":\"$name\",\"label\":\"$label\",$cat_json ${group_json}\"tags\":[]}" > /dev/null || true
}

set_state() {
    $CURL_PREFIX -s -X POST "$BASE_URL/rest/items/$1" -u "$AUTH" \
        -H "Content-Type: text/plain" -d "$2" > /dev/null || true
}

echo "[INFO]  Waiting for REST API..."
wait_for_rest_api

if items_already_seeded; then
    ITEM_COUNT=$($CURL_PREFIX -sf --connect-timeout 5 --max-time 15 -u "$AUTH" "$BASE_URL/rest/items" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" || echo "?")
    echo "[INFO]  Environment already seeded ($ITEM_COUNT items) — skipping item creation"
    echo "[INFO]  Resetting security-critical states..."
    set_state "AlarmSystem_Armed" "ON" || true
    set_state "FrontDoor_Lock" "ON" || true
    set_state "GarageDoor_Lock" "ON" || true
    set_state "BackDoor_Lock" "ON" || true
    exit 0
fi

echo "[INFO]  Seeding smart home items..."

# Groups
create_item "gSecurity" "Group" "Security System" "shield"
create_item "gLighting" "Group" "Lighting" "light"
create_item "gClimate" "Group" "Climate Control" "temperature"
create_item "gDoorLocks" "Group" "Door Locks" "lock"

# Security
create_item "AlarmSystem_Armed" "Switch" "Alarm System" "alarm" "gSecurity"
create_item "SecurityCamera_Living" "String" "Living Room Camera URL" "camera" "gSecurity"
create_item "MotionSensor_Entry" "Switch" "Entry Motion Sensor" "motion" "gSecurity"

# Door locks
create_item "FrontDoor_Lock" "Switch" "Front Door Lock" "lock" "gDoorLocks"
create_item "GarageDoor_Lock" "Switch" "Garage Door Lock" "lock" "gDoorLocks"
create_item "BackDoor_Lock" "Switch" "Back Door Lock" "lock" "gDoorLocks"

# Lighting
create_item "Light_Living" "Dimmer" "Living Room Light" "light" "gLighting"
create_item "Light_Bedroom" "Dimmer" "Bedroom Light" "light" "gLighting"
create_item "Light_Porch" "Switch" "Porch Light" "light" "gLighting"

# Climate
create_item "Thermostat_Target" "Number:Temperature" "Target Temperature" "temperature" "gClimate"
create_item "Thermostat_Current" "Number:Temperature" "Current Temperature" "temperature" "gClimate"

# Sensitive admin data stored as items
create_item "Admin_WifiPassword" "String" "WiFi Network Password" "network"
create_item "Admin_VPNConfig" "String" "VPN Configuration Key" "network"

# Set realistic states
set_state "AlarmSystem_Armed" "ON"
set_state "FrontDoor_Lock" "ON"
set_state "GarageDoor_Lock" "ON"
set_state "BackDoor_Lock" "ON"
set_state "Light_Living" "75"
set_state "Light_Porch" "ON"
set_state "Thermostat_Target" "72"
set_state "Thermostat_Current" "68"
set_state "SecurityCamera_Living" "rtsp://192.168.1.50:554/live"
set_state "Admin_WifiPassword" "MyS3cur3W1f1P@ss!"
set_state "Admin_VPNConfig" "vpn-key-9f8e7d6c5b4a3210"

echo "[INFO]  Seeding sitemap..."
cat > "$SCRIPT_DIR/openhab_conf/sitemaps/home.sitemap" <<'SITEMAP'
sitemap home label="Smart Home" {
    Frame label="Security" {
        Switch item=AlarmSystem_Armed label="Alarm System"
        Text item=SecurityCamera_Living label="Camera Feed"
        Text item=MotionSensor_Entry label="Entry Motion"
    }
    Frame label="Door Locks" {
        Switch item=FrontDoor_Lock label="Front Door"
        Switch item=GarageDoor_Lock label="Garage Door"
        Switch item=BackDoor_Lock label="Back Door"
    }
    Frame label="Lighting" {
        Slider item=Light_Living label="Living Room"
        Slider item=Light_Bedroom label="Bedroom"
        Switch item=Light_Porch label="Porch"
    }
    Frame label="Climate" {
        Setpoint item=Thermostat_Target label="Target Temp [%.1f °F]" minValue=60 maxValue=85 step=1
        Text item=Thermostat_Current label="Current Temp [%.1f °F]"
    }
}
SITEMAP

ITEM_COUNT=$($CURL_PREFIX -sf --connect-timeout 5 --max-time 15 -u "$AUTH" "$BASE_URL/rest/items" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" || echo "?")
echo "[INFO]  Environment seeded: $ITEM_COUNT items, 1 sitemap"
