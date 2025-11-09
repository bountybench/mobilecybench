#!/usr/bin/env bash
# Cleanup script for Meshtastic Android app
# Removes Docker containers and temporary files

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[cleanup] Stopping Meshtastic mesh network simulators..."

cd "$SCRIPT_DIR"

# Stop and remove Docker containers
docker-compose down -v 2>/dev/null || echo "[cleanup] No containers to stop"

# Remove any Docker volumes
docker volume ls -q | grep meshtastic | xargs docker volume rm 2>/dev/null || true

# Remove fake agent logs
if [ -f "vuln_scenarios/vuln_scenario_0/fake_agent_log.log" ]; then
    echo "[cleanup] Removing fake agent log..."
    rm -f "vuln_scenarios/vuln_scenario_0/fake_agent_log.log"
fi

# Note: We do NOT remove the APK file as per MobileCybench conventions
# Users may want to keep the built APK for testing

echo "[cleanup] Cleanup complete"
echo "[cleanup] Note: APK file preserved (not removed)"
