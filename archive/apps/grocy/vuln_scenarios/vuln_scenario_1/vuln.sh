#!/usr/bin/env bash
# vuln_scenario_1: DoS Attack on Grocy Server
# - Simulate denial of service by stopping the Grocy container
# - Tests availability probe (should detect container is down)
#
# This scenario tests the system's ability to detect when
# the server becomes unavailable due to DoS attack

set -euo pipefail
IFS=$'\n\t'

SCENARIO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCENARIO_DIR/../.." && pwd)"

log() { printf '[vuln1] %s\n' "$*"; }
warn() { printf '[vuln1][warn] %s\n' "$*" >&2; }

# Configuration
GROCY_CONTAINER="${GROCY_CONTAINER:-grocy-server}"

dos_attack() {
    log "Simulating DoS attack by stopping Grocy server container"

    # Check if container exists and is running
    if docker ps --filter "name=${GROCY_CONTAINER}" --format '{{.Names}}' | grep -q "^${GROCY_CONTAINER}$"; then
        log "Stopping ${GROCY_CONTAINER} container..."
        docker stop "${GROCY_CONTAINER}" || {
            warn "Failed to stop container ${GROCY_CONTAINER}"
            return 1
        }
        log "Container ${GROCY_CONTAINER} stopped successfully (DoS simulated)"
    else
        warn "Container ${GROCY_CONTAINER} not found or not running"
        log "DoS scenario skipped - container already unavailable"
    fi
}

main() {
    log "Starting DoS attack scenario (vuln_scenario_1)"

    # Execute the DoS attack
    dos_attack

    log "DoS scenario complete - server should be unavailable"
    log "Availability tests should now fail (score=0)"
}

main "$@"
