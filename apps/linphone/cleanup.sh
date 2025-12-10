#!/bin/bash
set -e

echo "Removing secret/temporary files..."
rm -f secrets.sql
rm -f secrets.json
rm -f baseline.json

echo "Removing scores..."
rm -f scores.json

echo "Removing log files recursively..."
find . -type f -name "*.log" -delete

echo "Removing txt files recursively..."
find . -type f -name "*.txt" -delete

adb logcat -c

echo "Taking down containers..."
docker compose down