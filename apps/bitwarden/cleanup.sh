#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_NAME="com.x8bit.bitwarden.dev"

echo "=== Cleaning up Bitwarden ==="

# 1. Reset data files to placeholder state (satisfied CI validator)
echo "[INFO] Resetting data files..."
echo '{"users": [], "ciphers": [], "flags": []}' > "$SCRIPT_DIR/secrets.json"
echo '{"flags": []}' > "$SCRIPT_DIR/flags.json"
rm -f "$SCRIPT_DIR/codebase/user.properties"

# 2. Remove generated evaluation logs/scores
echo "[INFO] Removing evaluation artifacts..."
rm -f "$SCRIPT_DIR/scores.json"
rm -f "$SCRIPT_DIR/generic_scores.json"
rm -f "$SCRIPT_DIR/vuln_scenarios/vuln_scenario_0/agent_log.log"

# 3. Uninstall the app from emulator
echo "[INFO] Uninstalling APK from emulator ($PKG_NAME)..."
adb uninstall "$PKG_NAME" || echo "[WARNING] Failed to uninstall or app not found."

# 4. Tear down backend containers
echo "[INFO] Cleaning up Docker environment..."
docker compose -f "$SCRIPT_DIR/docker-compose.yml" down -v

echo "=== Bitwarden Cleanup Complete ==="
