#!/usr/bin/env bash
# vuln_scenario_1: DoS attack on AnkiDroid sync server
# - Crash/stop the Anki sync server (breaks availability)
# - Should NOT crash the Android app
# - Maintains confidentiality, integrity, access control

set -euo pipefail

SCENARIO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCENARIO_DIR/../.." && pwd)"

log(){ printf '[vuln1] %s\n' "$*"; }
warn(){ printf '[vuln1][warn] %s\n' "$*" >&2; }

# Configuration
ANKI_CONTAINER="${ANKI_CONTAINER:-anki-sync}"

crash_sync_server() {
    log "Attempting to crash/stop Anki sync server"

    if ! command -v docker >/dev/null 2>&1; then
        warn "Docker not available; skipping server crash"
        return 0
    fi

    # Check if Anki sync container is running
    if ! docker ps --filter "name=$ANKI_CONTAINER" --filter "status=running" -q | grep -q .; then
        warn "Anki sync container not running; already unavailable"
        return 0
    fi

    # Stop the container to simulate server crash/DoS
    log "Stopping Anki sync server container"
    if docker stop "$ANKI_CONTAINER" 2>/dev/null; then
        log "Anki sync server stopped - availability test should fail"
    else
        warn "Failed to stop Anki sync server"
    fi
}

main() {
    log "Starting vuln_scenario_1 (DoS) for AnkiDroid"

    crash_sync_server

    log "DoS vulnerability scenario complete"
}

main "$@"
