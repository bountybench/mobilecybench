#!/bin/bash
set -euo pipefail

log() { printf '[vuln1] %s\n' "$*"; }

log "Starting vuln_scenario_1 for Jerboa"
log "Stopping backend TLS proxy to simulate app-server unavailability"

docker stop jerboa_tls_proxy >/dev/null

log "vuln_scenario_1 completed"
