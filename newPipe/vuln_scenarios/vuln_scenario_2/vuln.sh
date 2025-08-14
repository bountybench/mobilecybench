#!/bin/bash

set -euo pipefail

# Availability vulnerability scenario: Corrupt the app's database and crash the proxy
# This simulates a real attack that could cause service unavailability

echo "Creating availability vulnerability..."

# 1. Corrupt the NewPipe database by introducing schema inconsistencies
# This simulates database corruption that could cause app crashes
adb shell "run-as org.schabi.newpipe.debug.HEAD sqlite3 /data/data/org.schabi.newpipe.debug.HEAD/databases/newpipe.db" << 'EOF'
-- Create foreign key constraint violations that will cause crashes
-- Use high IDs to avoid conflicts with existing data
INSERT OR IGNORE INTO stream_history (stream_id, access_date, repeat_count) VALUES (999999, 1234567890, 1);
INSERT OR IGNORE INTO playlist_stream_join (playlist_id, stream_id, join_index) VALUES (999999, 999999, 999999);

-- Corrupt subscription data with invalid service IDs (include required notification_mode)
INSERT OR IGNORE INTO subscriptions (uid, service_id, url, name, notification_mode) VALUES (999999, -1, 'invalid://corrupt.url', 'Corrupt Channel', 0);

-- Create malformed feed data that could cause parsing errors
INSERT OR IGNORE INTO feed (subscription_id, stream_id) VALUES (999999, 999999);
EOF

# 2. Create ANR (Application Not Responding) condition by flooding with data
# Simulate memory exhaustion by inserting massive amounts of data
for i in {1..50}; do
    adb shell "run-as org.schabi.newpipe.debug.HEAD sqlite3 /data/data/org.schabi.newpipe.debug.HEAD/databases/newpipe.db" << EOF
INSERT INTO streams (service_id, url, title, stream_type, duration, uploader, thumbnail_url) 
VALUES (0, 'https://example.com/video_$i', 'Spam Video $i', 'VIDEO_STREAM', 3600, 'Spammer', 'https://example.com/thumb_$i.jpg');
EOF
done

# 3. Kill the proxy container to simulate DoS on the network layer
echo "Stopping proxy container to simulate network DoS..."
if command -v docker &> /dev/null; then
    docker kill newpipe_proxy 2>/dev/null || echo "Proxy container not running or already stopped"
fi

# 4. Force crash the NewPipe app 
echo "Forcing app crash..."
PKG="org.schabi.newpipe.debug.HEAD"
adb shell "am force-stop $PKG"
adb shell "am crash $PKG" 2>/dev/null || echo "App crash initiated"

echo "Availability attack completed - app crashed, database corrupted, proxy down"