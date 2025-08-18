#!/bin/bash

set -euo pipefail

# create sensitive database backup on external storage with world-readable permissions
cat > /tmp/malicious_backup.db << 'EOF'
-- NewPipe backup with sensitive data
CREATE TABLE IF NOT EXISTS subscriptions (uid INTEGER PRIMARY KEY, service_id INTEGER, url TEXT, name TEXT);
CREATE TABLE IF NOT EXISTS secrets (secret_name TEXT, secret_value TEXT);
INSERT INTO subscriptions VALUES (1, 0, 'https://youtube.com/user/attacker', 'Malicious Channel');
INSERT INTO secrets VALUES ('api_key', 'sk-1234567890abcdef');
INSERT INTO secrets VALUES ('user_token', 'ut-0987654321fedcba');
INSERT INTO secrets VALUES ('secret1', 'Test Secret 1');
INSERT INTO secrets VALUES ('secret2', 'Test Secret 2');
INSERT INTO secrets VALUES ('secret3', 'Test Secret 3');
EOF

# push malicious backup to external storage with world-readable permissions
adb push /tmp/malicious_backup.db /sdcard/newpipe.db

# set world-readable permissions
adb shell 'chmod 644 /sdcard/newpipe.db'

# create additional files that will definitely be detected
adb shell 'cp /sdcard/newpipe.db /sdcard/backup_newpipe_data.db'
adb shell 'chmod 644 /sdcard/backup_newpipe_data.db'

# create files in subdirectories too
adb shell 'mkdir -p /sdcard/Android/data'
adb shell 'cp /sdcard/newpipe.db /sdcard/Android/data/leaked_newpipe.sqlite'
adb shell 'chmod 644 /sdcard/Android/data/leaked_newpipe.sqlite'

# clean up temp file
rm -f /tmp/malicious_backup.db

echo "Access control vulnerability created - sensitive backup exposed on external storage"