#!/bin/bash
set -e

echo "Cleaning up Thunderbird environment"
echo "==================="

echo "Stopping all services..."
docker compose down -v

echo "Removing any dangling containers..."
docker container prune -f

APK_PATH="thunderbird.apk" 
if [ -f "$APK_PATH" ]; then
    echo "Removing downloaded APK: $APK_PATH"
    rm -f "$APK_PATH"
fi
 
if [ -f "scores.json" ]; then
    echo "Removing scores: scores.json"
    rm -f "scores.json"
fi

echo "Removing exploit log files ..."
find . -type f -name "fake_agent_log.log" -delete

echo "Cleanup complete!" 
echo "==================="