#!/bin/bash
set -e

echo "Cleaning up Tinode environment"
echo "==================="

echo "Stopping all services..."
docker compose down -v

echo "Removing any dangling containers..."
docker container prune -f

APK_PATH="tindroid-debug.apk" # should match APK_PATH in setup_app_apklink.sh
if [ -f "$APK_PATH" ]; then
    echo "Removing downloaded APK: $APK_PATH"
    rm -f "$APK_PATH"
fi

if [ -f "secrets.json" ]; then
    echo "Removing generated secrets: secrets.json"
    rm -f "secrets.json"
fi

if [ -f ".env" ]; then
    echo "Removing generated environment variables: .env"
    rm -f ".env"
fi

if [ -f "init-db.sql" ]; then
    echo "Removing generated db init script: init-db.sql"
    rm -f "init-db.sql"
fi

if [ -f "seed_secrets.sql" ]; then
    echo "Removing generated seed DB: seed_secrets.sql"
    rm -f "seed_secrets.sql"
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