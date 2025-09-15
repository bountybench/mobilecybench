#!/bin/bash
set -e

echo "Cleaning up Home Assistant environment"
echo "==================="

echo "Stopping emulator if running..."
if [[ -z "${CI:-}" && -z "${GITHUB_ACTIONS:-}" ]]; then
    ../../stop_emulator.sh || true
fi

echo "Removing config files from the HA app"
sudo chmod -R u+w config && sudo rm -rf config

echo "Stopping all services..."
docker compose down -v

echo "Removing any dangling containers..."
docker container prune -f

echo "Removing Docker image..."
docker image rm -f ghcr.io/home-assistant/home-assistant:stable -f || true

APK_PATH="Home Assistant.apk"
if [ -f "$APK_PATH" ]; then
    echo "Removing downloaded APK: $APK_PATH"
    rm -f "$APK_PATH"
fi

if [ -f "scores.json" ]; then
    echo "Removing scores: scores.json"
    rm -f "scores.json"
fi

echo "Removing log files recursively..."
find . -type f -name "*.log" -delete

echo "Remove changes to the codebase submodule..."
CODEBASE_DIR="$(dirname "$0")/codebase"
cd "$CODEBASE_DIR" && git reset --hard && git clean -fdx && cd - > /dev/null

echo "Cleanup complete!" 
echo "==================="