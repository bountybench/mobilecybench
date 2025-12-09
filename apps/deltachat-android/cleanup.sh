#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

rm -f "$SCRIPT_DIR/scores.json"
rm -f "$SCRIPT_DIR/generic_scores.json"

# Stop and remove docker-mailserver containers
docker compose -f "$SCRIPT_DIR/docker-compose.yml" down -v

# Clean up mail server data volumes (files may be owned by root from container)
# Use docker to remove with proper permissions, fallback to regular rm
if [ -d "$SCRIPT_DIR/docker-data" ]; then
    docker run --rm -v "$SCRIPT_DIR/docker-data:/data" alpine rm -rf /data/* 2>/dev/null || true
    rm -rf "$SCRIPT_DIR/docker-data" 2>/dev/null || true
fi

# Clean up vuln scenario backups
rm -f "$SCRIPT_DIR/vuln_scenarios/vuln_scenario_0/accounts.json.bak"
rm -f "$SCRIPT_DIR/vuln_scenarios/vuln_scenario_0/fake_agent_log.log"
