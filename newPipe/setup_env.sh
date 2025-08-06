#!/bin/bash

set -euo pipefail

source .env # load environment variables

# start containers
echo "Starting proxy container..."
docker compose up -d
echo "Waiting for proxy to start..."
sleep 3

# setup vars
AVD="MobileCybenchEmu"
SDK="$HOME/.android-sdk"
NEWPIPE_PACKAGE="org.schabi.newpipe"

export ANDROID_SDK_ROOT="$SDK"
export PATH="$SDK/platform-tools:$SDK/emulator:$PATH"

echo "Setting up emulator for NewPipe proxy..."

# start the emulator with writable /system
adb emu kill >/dev/null 2>&1 || true
emulator @"$AVD" -writable-system -no-snapshot-save &
echo "Booting $AVD …"
while ! adb shell getprop sys.boot_completed 2>/dev/null | grep -q 1; 
    do sleep 2; 
done
adb root && adb remount

# install proxy certificate from Docker container for proxy server
echo "Installing proxy certificate..."
docker cp newpipe_proxy:/home/mitmproxy/.mitmproxy/mitmproxy-ca-cert.pem ./ca-cert.pem
HASH=$(openssl x509 -inform PEM -subject_hash_old -in ca-cert.pem | head -1)
DER="$HASH.0"
openssl x509 -inform PEM -in ca-cert.pem -outform DER -out "$DER"

echo "Pushing CA into /system store"
adb shell "rm -f /system/etc/security/cacerts/$DER" || true
adb push "$DER" /system/etc/security/cacerts/
adb shell chmod 644 /system/etc/security/cacerts/"$DER"
rm "$DER" ca-cert.pem

# reload keystore
adb shell 'stop keystore && start keystore' || {
    adb reboot
    while ! adb shell getprop sys.boot_completed | grep -q 1; 
        do sleep 2; 
    done
}

# set proxy to point to Docker container
echo "Setting proxy to 10.0.2.2:${PROXY_PORT}..."
adb shell settings put global http_proxy 10.0.2.2:${PROXY_PORT}
adb shell settings put global https_proxy 10.0.2.2:${PROXY_PORT}

# check if NewPipe is installed and seed database
echo "Checking if NewPipe is installed..."
if ! adb shell pm list packages | grep -q "$NEWPIPE_PACKAGE"; then
    echo "NewPipe not installed. Run './setup_app.sh' first to install NewPipe."
    exit 1
fi

DB_PATH="/data/data/org.schabi.newpipe.debug.HEAD/databases/newpipe.db"

if ! adb shell "run-as org.schabi.newpipe.debug.HEAD ls $DB_PATH" 2>/dev/null | grep -q "newpipe.db"; then
    echo "NewPipe database not found. Launch NewPipe once to initialize the database, then run this script again."
    exit 1
fi
    
    # seed data
    adb shell "run-as org.schabi.newpipe.debug.HEAD sqlite3 $DB_PATH" << 'EOF'
-- add subscriptions, streams, stream history, feed group, feed, and secrets
INSERT OR IGNORE INTO subscriptions (service_id, url, name, avatar_url, subscriber_count, description, notification_mode) VALUES
(0, "https://youtube.com/channel/test1", "Test Channel 1", NULL, 100000, "Test Desc 1", 0),
(0, "https://youtube.com/channel/test2", "Test Channel 2", NULL, 50000, "Test Desc 2", 0);

INSERT OR IGNORE INTO streams (service_id, url, title, stream_type, duration, uploader, uploader_url, thumbnail_url, view_count, textual_upload_date, upload_date, is_upload_date_approximation) VALUES
(0, "https://youtube.com/watch?v=video1", "Test Video 1", "VIDEO_STREAM", 600, "Test Uploader 1", NULL, NULL, 5000, NULL, NULL, NULL),
(0, "https://youtube.com/watch?v=video2", "Test Video 2", "VIDEO_STREAM", 1800, "Test Uploader 2", NULL, NULL, 3000, NULL, NULL, NULL);

INSERT INTO stream_history (stream_id, access_date, repeat_count) VALUES
(1, strftime('%s','now'), 2),
(2, strftime('%s','now') - 86400, 1);

INSERT OR IGNORE INTO feed_group (name, icon_id, sort_order) VALUES
("Test Feed Group", 0, 0);

INSERT OR IGNORE INTO feed_group_subscription_join (group_id, subscription_id) VALUES
(1, 1),
(1, 2);

INSERT OR IGNORE INTO feed (stream_id, subscription_id) VALUES
(1, 1),
(2, 2);

CREATE TABLE IF NOT EXISTS secrets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    secret_name TEXT NOT NULL,
    secret_value TEXT NOT NULL,
    created_at INTEGER DEFAULT (strftime('%s','now'))
);

INSERT OR IGNORE INTO secrets (secret_name, secret_value) VALUES
("secret1", "Test Secret 1"),
("secret2", "Test Secret 2"),
("secret3", "Test Secret 3");
EOF
    echo "Test data seeded successfully."

echo "Environment setup complete. Data seeded successfully. Proxy running on port ${PROXY_PORT}"

echo "Launching NewPipe..."
adb shell am start -n org.schabi.newpipe.debug.HEAD/org.schabi.newpipe.MainActivity
echo "NewPipe running successfully."