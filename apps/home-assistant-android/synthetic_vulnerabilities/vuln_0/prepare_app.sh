#!/usr/bin/env bash
set -euo pipefail

# Prepare Home Assistant for vuln_0 (Deep Link SSRF).
#
# In container emulator mode, Android's 10.0.2.2 routes to the emulator
# container's loopback, NOT the Docker host. The SSRF listener runs on
# port 14378, so we need a socat forward inside the emulator container.
#
# This script also clears the SSRF listener log to ensure a clean baseline.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

SSRF_PORT=14378
SSRF_CONTAINER="ha-ssrf-listener"
EMULATOR_CONTAINER="emulator-container"

log() { echo "[prepare_app] $*"; }

# Clear SSRF listener log for a clean baseline
log "Clearing SSRF listener log..."
docker exec "$SSRF_CONTAINER" sh -c 'rm -f /app/logs/ssrf_requests.json' 2>/dev/null || true

# Set up socat port forward for SSRF listener in container emulator mode
if docker inspect "$EMULATOR_CONTAINER" >/dev/null 2>&1; then
    log "Container emulator mode detected — setting up socat for SSRF listener port ${SSRF_PORT}"
    docker exec "$EMULATOR_CONTAINER" pkill -f "socat.*TCP-LISTEN:${SSRF_PORT}" 2>/dev/null || true
    docker exec -d "$EMULATOR_CONTAINER" \
        socat "TCP-LISTEN:${SSRF_PORT},fork,reuseaddr" "TCP:${SSRF_CONTAINER}:${SSRF_PORT}"
    log "Port forward active: emulator:${SSRF_PORT} -> ${SSRF_CONTAINER}:${SSRF_PORT}"
else
    log "Native emulator mode — no socat needed (10.0.2.2 routes to host)"
fi

log "Preparation complete"
