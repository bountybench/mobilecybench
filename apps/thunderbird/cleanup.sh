#!/bin/bash
# =============================================================================
# Cleanup Script for Thunderbird Environment
# =============================================================================

set -e

echo "Cleaning up Thunderbird environment..."

# =============================================================================
# Stop Services
# =============================================================================

docker compose down -v
docker container prune -f

# =============================================================================
# Uninstall Android App
# =============================================================================

PACKAGE_NAME="net.thunderbird.android"
if adb shell pm list packages | grep -q "^package:$PACKAGE_NAME$"; then
    adb uninstall "$PACKAGE_NAME" || true
fi

adb logcat -c || true

# =============================================================================
# Remove Temporary Files
# =============================================================================

rm -f thunderbird.apk
rm -f scores.json
rm -f fake_agent_log.log

echo "Cleanup complete!"