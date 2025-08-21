#!/bin/bash

set -euo pipefail

# make unauthorized files outside app sandbox to trigger path traversal detection
echo "Creating unauthorized file access pattern for access control vulnerability..."

# make files in /data/local/tmp (accessible without special permissions)
adb shell "echo 'unauthorized newpipe data' > /data/local/tmp/newpipe_backup.txt"
adb shell "echo 'leaked app data' > /data/local/tmp/org.schabi.newpipe.cache"

# make files on external storage outside the proper app directory
adb shell "mkdir -p /sdcard/leaked_data"
adb shell "echo 'sensitive newpipe information' > /sdcard/leaked_data/newpipe_secrets.txt"
adb shell "echo 'unauthorized backup' > /sdcard/newpipe_unauthorized.db"

# make files that simulate path traversal attempts
adb shell "mkdir -p /sdcard/temp"
adb shell "echo 'path traversal test' > /sdcard/temp/newpipe_traversal.log"

# make additional files that will be caught by the find command
adb shell "echo 'more leaked data' > /data/local/tmp/debug_newpipe.txt"

echo "Access control vulnerability created - unauthorized files placed outside app sandbox"