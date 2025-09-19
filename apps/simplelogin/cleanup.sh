#!/bin/bash
set -e

echo "Cleaning up SimpleLogin environment"
echo "==================="

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
METADATA_FILE="$SCRIPT_DIR/metadata.json"

# Dynamic Docker Compose detection (v1/v2)
if docker compose version >/dev/null 2>&1; then
    DC="docker compose"
else
    DC="docker-compose"
fi

echo "Uninstalling SimpleLogin app..."
if [ -f "$METADATA_FILE" ]; then
    APP_ID=$(jq -r '.app_id' "$METADATA_FILE" 2>/dev/null || echo "")
    if [ -n "$APP_ID" ] && command -v adb >/dev/null 2>&1; then
        if adb devices | grep -q "device\|emulator"; then
            adb uninstall "$APP_ID" 2>/dev/null || echo "App may not have been installed"
            adb shell "am force-stop $APP_ID" 2>/dev/null || true
        fi
    fi
fi

echo "Stopping all services..."
$DC down -v 2>/dev/null || true

# Note: shared_net is now managed by docker-compose automatically

echo "Removing any dangling containers..."
docker container prune -f 2>/dev/null || true

if [ -f "secrets.json" ]; then
    echo "Removing generated secrets: secrets.json"
    rm -f "secrets.json"
fi

if [ -f "scores.json" ]; then
    echo "Removing scores: scores.json"
    rm -f "scores.json"
fi

if [ -f "apk_path.txt" ]; then
    echo "Removing APK path file: apk_path.txt"
    rm -f "apk_path.txt"
fi

if [ -f "integrity_baseline.json" ]; then
    echo "Removing integrity baseline: integrity_baseline.json"
    rm -f "integrity_baseline.json"
fi

echo "Removing test result files..."
rm -f *_results.json 2>/dev/null || true

echo "Removing log files..."
find . -type f -name "*.log" -delete 2>/dev/null || true
find . -type f -name "*.tmp" -delete 2>/dev/null || true

# Only remove codebase if explicitly requested (for full reset)
if [[ "${NUKE_SOURCE:-0}" == "1" ]] && [ -d "codebase" ]; then
    echo "Removing codebase directory (NUKE_SOURCE=1)..."
    rm -rf "codebase"
else
    echo "Keeping codebase directory for subsequent scenarios"
fi

echo "Cleanup complete!"
echo "==================="