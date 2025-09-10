#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# echo "[INFO] Removing secret files..."
rm -f "$SCRIPT_DIR/flags.json"
rm -f "$SCRIPT_DIR/secrets.json"
rm -f "$SCRIPT_DIR/codebase/user.properties"

echo "[INFO] Removing evaluating files..."
rm -f "$SCRIPT_DIR/scores.json"

echo "[INFO] Removing agent log..."
rm -f "$SCRIPT_DIR/vuln_scenarios/vuln_scenario_0/agent_log.log"

echo "[INFO] Removing apk files"
rm -f "$SCRIPT_DIR/bitwarden.apk"

echo "[INFO] Cleaning up environment..."
docker compose -f "$SCRIPT_DIR/docker-compose.yml" down -v
echo "[INFO] Environment cleaned up."