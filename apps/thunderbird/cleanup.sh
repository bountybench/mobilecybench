#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Cleaning up Thunderbird environment..."

# Stop services
docker compose -f "$SCRIPT_DIR/docker-compose.yml" down -v || true
docker rm -f tb-port-25-proxy 2>/dev/null || true
docker container prune -f || true

# Remove temporary files created by prepare_app.sh
adb shell rm -f /data/local/tmp/update_imap_port.sql 2>/dev/null || true

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
rm -rf "$SCRIPT_DIR/dms-config"

echo "Cleanup complete!"
