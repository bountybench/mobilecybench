#!/bin/bash

set -euo pipefail

DB_PATH="/data/data/org.schabi.newpipe.debug.HEAD/databases/newpipe.db"

# seed the database
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