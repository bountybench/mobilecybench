#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/utils.sh"

log_info "Stopping docker compose stacks..."
docker_compose_down

log_info "Removing files: scores.json baseline.json secrets.json"
rm -f scores.json baseline.json secrets.json vuln_scenarios/vuln_scenario_0/fake_agent_log.log wordpress.apk || true