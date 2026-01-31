#!/bin/bash
# Setup script: Creates a fake download entry for testing
# Run this BEFORE the exploit to set up the test environment

set -e

CONTENT_ID="https://funkwhale.example.com/api/v1/listen/12345"
DB_PATH="/data/data/audio.funkwhale.ffa/databases/exoplayer_internal.db"

# Ensure root access
adb root > /dev/null 2>&1 || true
sleep 1

# Create SQL file with the insert statement
cat > /tmp/insert_download.sql << 'EOF'
INSERT OR REPLACE INTO ExoPlayerDownloads (
    id, mime_type, uri, stream_keys, custom_cache_key, data, state,
    start_time_ms, update_time_ms, content_length, stop_reason,
    failure_reason, percent_downloaded, bytes_downloaded, key_set_id
) VALUES (
    'https://funkwhale.example.com/api/v1/listen/12345',
    'audio/mpeg',
    'https://funkwhale.example.com/api/v1/listen/12345',
    '', NULL,
    CAST('{"id":12345,"contentId":"https://funkwhale.example.com/api/v1/listen/12345","title":"Test Song","artist":"Test Artist","download":null}' AS BLOB),
    3, 1706659200000, 1706659200000, 1000000, 0, 0, 100.0, 1000000, X''
);
EOF

adb push /tmp/insert_download.sql /data/local/tmp/insert_download.sql > /dev/null
adb shell "sqlite3 $DB_PATH < /data/local/tmp/insert_download.sql"

# Verify insertion
COUNT=$(adb shell "sqlite3 $DB_PATH \"SELECT COUNT(*) FROM ExoPlayerDownloads WHERE id='$CONTENT_ID'\"")
if [ "$COUNT" -eq "1" ]; then
    echo "SUCCESS: Test download created"
    exit 0
else
    echo "FAILED: Could not create test download"
    exit 1
fi
