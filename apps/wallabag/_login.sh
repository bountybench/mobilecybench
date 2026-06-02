#!/usr/bin/env bash
# Install wallabag SharedPreferences logging the given user into the
# Android app. OAuth client id/secret and access/refresh tokens are
# resolved from the wallabag DB (issued during start_runtime.sh seeding),
# so this script is the single source of truth for the prefs file shape.
#
# Usage: _login.sh <username> <password>
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"

PACKAGE="fr.gaulupeau.apps.InThePoche"
PREFS_DIR="/data/data/$PACKAGE/shared_prefs"
PREFS_FILE="$PREFS_DIR/${PACKAGE}_preferences.xml"
SERVER_URL="https://10.0.2.2:8080"

if [ "$#" -ne 2 ]; then
    fatal "Usage: $(basename "$0") <username> <password>"
fi
USERNAME="$1"
PASSWORD="$2"

DB_STATE_JSON="$(
  WB_USER="$USERNAME" MSYS_NO_PATHCONV=1 docker exec -i -e WB_USER wallabag php <<'PHP'
<?php
$user_name = getenv("WB_USER");
$db = new PDO('sqlite:/var/www/wallabag/data/db/wallabag.sqlite');
$client = $db->query(
    "SELECT id, random_id, secret FROM wallabag_oauth2_clients WHERE name = 'mobilecybench' ORDER BY id DESC LIMIT 1"
)->fetch(PDO::FETCH_ASSOC);
$user_stmt = $db->prepare("SELECT id FROM wallabag_user WHERE username = ? ORDER BY id DESC LIMIT 1");
$user_stmt->execute([$user_name]);
$user = $user_stmt->fetch(PDO::FETCH_ASSOC);
if (!$client || !$user) {
    fwrite(STDERR, "Missing OAuth client or user row for {$user_name}\n");
    exit(1);
}
$access_stmt = $db->prepare("SELECT token FROM wallabag_oauth2_access_tokens WHERE user_id = ? AND client_id = ? ORDER BY id DESC LIMIT 1");
$access_stmt->execute([$user["id"], $client["id"]]);
$access = $access_stmt->fetch(PDO::FETCH_ASSOC);
$refresh_stmt = $db->prepare("SELECT token FROM wallabag_oauth2_refresh_tokens WHERE user_id = ? AND client_id = ? ORDER BY id DESC LIMIT 1");
$refresh_stmt->execute([$user["id"], $client["id"]]);
$refresh = $refresh_stmt->fetch(PDO::FETCH_ASSOC);
if (!$access || !$refresh) {
    fwrite(STDERR, "Missing OAuth token rows for {$user_name}\n");
    exit(1);
}
echo json_encode([
    "client_id" => $client["id"]."_".$client["random_id"],
    "client_secret" => $client["secret"],
    "access_token" => $access["token"],
    "refresh_token" => $refresh["token"],
]);
PHP
)"

CLIENT_ID="$(printf '%s' "$DB_STATE_JSON" | jq -r '.client_id')"
CLIENT_SECRET="$(printf '%s' "$DB_STATE_JSON" | jq -r '.client_secret')"
ACCESS_TOKEN="$(printf '%s' "$DB_STATE_JSON" | jq -r '.access_token')"
REFRESH_TOKEN="$(printf '%s' "$DB_STATE_JSON" | jq -r '.refresh_token')"

for v in CLIENT_ID CLIENT_SECRET ACCESS_TOKEN REFRESH_TOKEN; do
    val="${!v:-}"
    if [ -z "$val" ] || [ "$val" = "null" ]; then
        fatal "Failed to resolve $v from wallabag DB for user '$USERNAME'"
    fi
done

# `adb root` restarts adbd on CI images. A fixed sleep can race the restart and
# leave the next private-data command talking to a disappeared emulator.
adb root >/dev/null 2>&1 || true
adb wait-for-device >/dev/null 2>&1 || true
wait_for_device_boot 60 || fatal "Device not ready after adb root"

# Kill any running app process before overwriting prefs. SharedPreferences are
# cached in memory; if the process is alive, the running app keeps serving the
# old map and can write its cache back over the file on its next commit().
# Caller is responsible for relaunching when UI inspection is needed.
MSYS_NO_PATHCONV=1 adb shell "am force-stop $PACKAGE" >/dev/null 2>&1 || true

APP_UID="$(MSYS_NO_PATHCONV=1 adb shell stat -c '%u' "/data/data/$PACKAGE" | tr -d '\r')"
if ! [[ "${APP_UID:-}" =~ ^[0-9]+$ ]]; then
    fatal "Failed to determine wallabag app UID (got: ${APP_UID:-unset})"
fi

PREFS_TMP="$(mktemp)"
trap 'rm -f "$PREFS_TMP"' EXIT
cat > "$PREFS_TMP" <<PREFS_EOF
<?xml version="1.0" encoding="utf-8" standalone="yes" ?>
<map>
    <string name="connection.url">$SERVER_URL</string>
    <string name="connection.username">$USERNAME</string>
    <string name="connection.password">$PASSWORD</string>
    <string name="connection.api.clientID">$CLIENT_ID</string>
    <string name="connection.api.clientSecret">$CLIENT_SECRET</string>
    <string name="connection.api.accessToken">$ACCESS_TOKEN</string>
    <string name="connection.api.refreshToken">$REFRESH_TOKEN</string>
    <string name="connection.advanced.httpAuthUsername"></string>
    <string name="connection.advanced.httpAuthPassword"></string>
    <boolean name="internal.firstRun" value="false" />
    <boolean name="internal.configurationIsOk" value="true" />
    <int name="internal.preferencesVersion" value="100" />
    <boolean name="autoSync.onStartup.enabled" value="false" />
    <boolean name="autoSync.enabled" value="false" />
    <long name="autoSync.interval" value="86400000" />
    <int name="autoSync.type" value="0" />
    <boolean name="autoSyncQueue.enabled" value="false" />
    <boolean name="imageCache.enabled" value="false" />
    <boolean name="sync.sweepingAfterFastSync.enabled" value="false" />
    <int name="ui.readingSpeed" value="200" />
    <string name="storage.dbPath"></string>
</map>
PREFS_EOF

# Strip CR introduced by Git Bash heredocs; corrupt XML breaks the
# SharedPreferences parser silently and the app boots to the login screen.
sed -i 's/\r//' "$PREFS_TMP" 2>/dev/null || true

PREFS_HOST_PATH="$PREFS_TMP"
if command -v cygpath >/dev/null 2>&1; then
    PREFS_HOST_PATH="$(cygpath -w "$PREFS_TMP")"
fi

MSYS_NO_PATHCONV=1 adb push "$PREFS_HOST_PATH" "/data/local/tmp/wallabag_prefs.xml" >/dev/null
MSYS_NO_PATHCONV=1 adb shell "mkdir -p $PREFS_DIR && mv /data/local/tmp/wallabag_prefs.xml $PREFS_FILE"
MSYS_NO_PATHCONV=1 adb shell "chown $APP_UID:$APP_UID $PREFS_FILE" >/dev/null 2>&1 || true
MSYS_NO_PATHCONV=1 adb shell "chmod 660 $PREFS_FILE" >/dev/null 2>&1 || true
MSYS_NO_PATHCONV=1 adb shell "restorecon $PREFS_FILE" >/dev/null 2>&1 || true
MSYS_NO_PATHCONV=1 adb shell "test -f $PREFS_FILE" >/dev/null \
    || fatal "Wallabag prefs file missing after login install"

log_info "Wallabag login installed for $USERNAME."
