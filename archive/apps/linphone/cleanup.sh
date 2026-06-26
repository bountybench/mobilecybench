#!/bin/bash
set -e

echo "Removing temporary files..."
rm -f secrets.sql
rm -f baseline.json

echo "Removing scores..."
rm -f scores.json

echo "Removing log files recursively..."
find . -type f -name "*.log" -delete

echo "Removing txt files recursively..."
find . -type f -name "*.txt" -delete

adb logcat -c

echo "Uninstalling linphone..."
adb uninstall org.linphone || true

echo "Taking down containers..."
docker compose down