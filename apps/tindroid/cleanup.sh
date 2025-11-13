#!/bin/bash
set -e

echo "Cleaning up Tinode environment"
echo "==================="

echo "Stopping all services..."
docker compose down -v

echo "Removing any dangling containers..."
docker container prune -f

echo "Uninstalling Android app..."
adb uninstall co.tinode.tindroidx 2>/dev/null || echo "App not installed or already uninstalled"

APK_PATH="tindroid-debug.apk" # should match APK_PATH in setup_app_apklink.sh
if [ -f "$APK_PATH" ]; then
    echo "Removing downloaded APK: $APK_PATH"
    rm -f "$APK_PATH"
fi

if [ -f ".env" ]; then
    echo "Removing generated environment variables: .env"
    rm -f ".env"
fi

if [ -f "init-db.sql" ]; then
    echo "Removing generated db init script: init-db.sql"
    rm -f "init-db.sql"
fi

if [ -f "seed_db.sql" ]; then
    echo "Removing generated seed DB: seed_db.sql"
    rm -f "seed_db.sql"
fi

if [ -f "scores.json" ]; then
    echo "Removing scores: scores.json"
    rm -f "scores.json"
fi

echo "Removing log files recursively..."
find . -type f -name "*.log" -delete

echo "Removing virtual environment..."
rm -rf ./venv

echo "Cleanup complete!" 
echo "==================="