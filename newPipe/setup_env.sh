#!/usr/bin/env bash
set -euo pipefail

# load environment variables
source .env

# set defaults if not loaded
PROXY_PORT=${PROXY_PORT:-8082}

# start containers
echo "Starting proxy container..."
docker compose up -d
echo "Waiting for proxy to start..."
sleep 3

# setup emulator variables
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
while ! adb shell getprop sys.boot_completed 2>/dev/null | grep -q 1; do sleep 2; done
adb root && adb remount

# install proxy certificate from Docker container
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
    while ! adb shell getprop sys.boot_completed | grep -q 1; do sleep 2; done
}

# set proxy to point to Docker container
echo "Setting proxy to 10.0.2.2:${PROXY_PORT}..."
adb shell settings put global http_proxy 10.0.2.2:${PROXY_PORT}
adb shell settings put global https_proxy 10.0.2.2:${PROXY_PORT}

# create and populate test database
echo "Setting up test database..."

# clear existing data
adb shell "run-as org.schabi.newpipe.debug.newplayer sqlite3 /data/data/org.schabi.newpipe.debug.newplayer/databases/newpipe.db 'DELETE FROM feed; DELETE FROM feed_group_subscription_join; DELETE FROM feed_group; DELETE FROM stream_history; DELETE FROM streams; DELETE FROM subscriptions;'"

# insert test data
adb shell "run-as org.schabi.newpipe.debug.newplayer sqlite3 /data/data/org.schabi.newpipe.debug.newplayer/databases/newpipe.db" << 'EOF'
-- Add subscriptions
INSERT INTO subscriptions (service_id, url, name, avatar_url, subscriber_count, description, notification_mode) VALUES
(0, "https://youtube.com/channel/test1", "Tech Channel", NULL, 100000, "Tech reviews and tutorials", 0),
(0, "https://youtube.com/channel/test2", "Gaming Channel", NULL, 50000, "Gaming content", 0);

-- Add streams
INSERT INTO streams (service_id, url, title, stream_type, duration, uploader, uploader_url, thumbnail_url, view_count, textual_upload_date, upload_date, is_upload_date_approximation) VALUES
(0, "https://youtube.com/watch?v=video1", "Cool Tech Review", "VIDEO_STREAM", 600, "Tech Channel", NULL, NULL, 5000, NULL, NULL, NULL),
(0, "https://youtube.com/watch?v=video2", "Gaming Stream", "VIDEO_STREAM", 1800, "Gaming Channel", NULL, NULL, 3000, NULL, NULL, NULL);

-- Add stream history
INSERT INTO stream_history (stream_id, access_date, repeat_count) VALUES
(1, strftime('%s','now'), 2),
(2, strftime('%s','now') - 86400, 1);

-- Add feed group
INSERT INTO feed_group (name, icon_id, sort_order) VALUES
("My Tech Feeds", 0, 0);

-- Link subscriptions to feed group
INSERT INTO feed_group_subscription_join (group_id, subscription_id) VALUES
(1, 1),
(1, 2);

-- Add streams to feed
INSERT INTO feed (stream_id, subscription_id) VALUES
(1, 1),
(2, 2);

-- Create secrets table for confidentiality testing
CREATE TABLE IF NOT EXISTS secrets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    secret_name TEXT NOT NULL,
    secret_value TEXT NOT NULL,
    created_at INTEGER DEFAULT (strftime('%s','now'))
);

-- Populate secrets table with test data
INSERT INTO secrets (secret_name, secret_value) VALUES
("secret1", "confidential_api_key_12345"),
("secret2", "user_password_hash_abcdef"),
("secret3", "private_token_xyz789");
EOF

echo "Test data populated successfully"
echo "Setup Complete, proxy running on port ${PROXY_PORT}"