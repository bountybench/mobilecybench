#!/usr/bin/env bash
set -euo pipefail

echo "Cleaning up Thunderbird environment..."

# Stop services
docker compose down -v || true
docker container prune -f || true

# Uninstall Android app
PACKAGE_NAME="net.thunderbird.android"
if adb shell pm list packages | grep -q "^package:$PACKAGE_NAME$"; then
    adb uninstall "$PACKAGE_NAME" || true
fi
adb logcat -c || true

# Remove generated artifacts and temporary files
rm -f thunderbird.apk
rm -f scores.json
rm -f fake_agent_log.log
rm -rf dms-config

echo "Cleanup complete!"
