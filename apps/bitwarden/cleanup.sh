#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# echo "[INFO] Removing secret files..."
rm "$SCRIPT_DIR/flags.json" || true
rm "$SCRIPT_DIR/secrets.json" || true
rm "$SCRIPT_DIR/codebase/user.properties" || true

echo "[INFO] Removing evaluating files..."
rm "$SCRIPT_DIR/scores.json" || true

echo "[INFO] Removing agent log..."
rm "$SCRIPT_DIR/vuln_scenarios/vuln_scenario_0/agent_log.log" || true

echo "[INFO] Removing apk files"
rm "$SCRIPT_DIR/bitwarden.apk" || true

echo "[INFO] Cleaning up environment..."
docker compose down -v
echo "[INFO] Environment cleaned up."