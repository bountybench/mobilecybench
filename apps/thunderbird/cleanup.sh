#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Cleaning up Thunderbird environment..."

# Stop services
docker compose -f "$SCRIPT_DIR/docker-compose.yml" down -v || true
docker rm -f tb-port-25-proxy 2>/dev/null || true
docker rm -f thunderbird-mitm 2>/dev/null || true
docker container prune -f || true

# Remove ADB reverse tunnel and stale iptables rules
adb reverse --remove-all 2>/dev/null || true
adb root 2>/dev/null && sleep 1
adb shell iptables -t nat -D OUTPUT -p tcp -d 10.0.2.2 --dport 993 \
    -j DNAT --to-destination 10.0.2.2:1993 2>/dev/null || true
adb shell rm -f /data/local/tmp/update_imap_port.sql 2>/dev/null || true
adb unroot 2>/dev/null || true

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
