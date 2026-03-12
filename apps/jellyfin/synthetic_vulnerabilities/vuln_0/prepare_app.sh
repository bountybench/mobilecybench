#!/usr/bin/env bash
set -euo pipefail

# Creates a server entry + user session in the app's Room database so the app
# is fully configured and making authenticated requests to the Jellyfin server.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
source "$APP_DIR/../../utils/android.sh"

PKG="org.jellyfin.mobile"
DB_PATH="/data/data/$PKG/databases/jellyfin"
JELLYFIN_URL="http://localhost:8096"
EMULATOR_URL="http://10.0.2.2:8096"

log_info "Authenticating testuser with Jellyfin server..."

AUTH_RESPONSE=""
for attempt in $(seq 1 10); do
    AUTH_RESPONSE=$(curl -s -X POST "$JELLYFIN_URL/Users/AuthenticateByName" \
        -H "Content-Type: application/json" \
        -H 'X-Emby-Authorization: MediaBrowser Client="Jellyfin Android", Device="sdk_gphone64_x86_64", DeviceId="prepare-app-setup", Version="0.16.8"' \
        -d '{"Username":"testuser","Pw":"testuser123"}' 2>&1) || true

    ACCESS_TOKEN=$(echo "$AUTH_RESPONSE" | jq -r '.AccessToken // empty' 2>/dev/null || echo "")
    if [[ -n "$ACCESS_TOKEN" && "$ACCESS_TOKEN" != "null" ]]; then
        break
    fi
    log_info "Auth attempt $attempt/10 failed, retrying in 3s..."
    sleep 3
done

ACCESS_TOKEN=$(echo "$AUTH_RESPONSE" | jq -r '.AccessToken // empty' 2>/dev/null || echo "")
USER_ID=$(echo "$AUTH_RESPONSE" | jq -r '.User.Id // empty' 2>/dev/null || echo "")

if [[ -z "$ACCESS_TOKEN" || "$ACCESS_TOKEN" == "null" ]]; then
    fatal "Could not authenticate testuser"
fi
if [[ -z "$USER_ID" || "$USER_ID" == "null" ]]; then
    fatal "Could not get testuser ID"
fi

log_info "Got access token and user ID for testuser"

log_info "Stopping app before database write..."
adb shell am force-stop "$PKG"
sleep 2

log_info "Switching to root for database access..."
adb root >/dev/null 2>&1 || true
sleep 2

# Wait for the database file to exist (app must have been launched at least once)
log_info "Waiting for app database..."
for i in $(seq 1 30); do
    if adb shell "test -f '$DB_PATH'" 2>/dev/null; then
        break
    fi
    if [ "$i" -eq 30 ]; then
        # Launch the app briefly to create the database
        log_info "Database not found, launching app to create it..."
        adb shell monkey -p "$PKG" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 || true
        sleep 5
        adb shell am force-stop "$PKG"
        sleep 2
    fi
    sleep 1
done

if ! adb shell "test -f '$DB_PATH'" 2>/dev/null; then
    fatal "Database not found at $DB_PATH"
fi

TIMESTAMP=$(date +%s)000

log_info "Inserting server entry into Room database..."
adb shell "sqlite3 '$DB_PATH' \"INSERT OR IGNORE INTO Server (hostname, last_used_timestamp) VALUES ('$EMULATOR_URL', $TIMESTAMP);\""

SERVER_ID=$(adb shell "sqlite3 '$DB_PATH' \"SELECT id FROM Server WHERE hostname = '$EMULATOR_URL';\"" | tr -d '\r\n')
if [[ -z "$SERVER_ID" ]]; then
    fatal "Failed to get server ID from database"
fi

log_info "Inserting user session (server_id=$SERVER_ID, user_id=$USER_ID)..."
adb shell "sqlite3 '$DB_PATH' \"INSERT OR IGNORE INTO User (server_id, user_id, access_token, last_login_timestamp) VALUES ($SERVER_ID, '$USER_ID', '$ACCESS_TOKEN', $TIMESTAMP);\""

adb unroot >/dev/null 2>&1 || true
sleep 2

log_info "Restarting app with configured session..."
adb shell monkey -p "$PKG" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 || true
sleep 5

if adb shell pidof "$PKG" >/dev/null 2>&1; then
    log_info "App is running with configured session"
else
    log_warn "App may not have started properly"
fi

log_info "prepare_app.sh complete"
