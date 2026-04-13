#!/usr/bin/env bash
set -euo pipefail

# Prepare Home Assistant for vuln_0 (Deep Link SSRF).
#
# In container emulator mode, Android's 10.0.2.2 routes to the emulator
# container's loopback, NOT the Docker host. The exploit uses
# https://10.0.2.2:14378, so we need a TCP forward inside the emulator
# container to the TLS proxy.
#
# This script also clears the SSRF listener log to ensure a clean baseline.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

SSRF_PORT=14378
SSRF_CONTAINER="ha-ssrf-listener"
SSRF_PROXY_CONTAINER="ha-ssrf-tls-proxy"
EMULATOR_CONTAINER="emulator-container"

log() { echo "[prepare_app] $*"; }

wait_healthy() {
    local container="$1"
    local timeout="${2:-30}"
    local start_ts
    start_ts=$(date +%s)

    while true; do
        local status
        status=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container" 2>/dev/null || true)
        if [[ "$status" == "healthy" || "$status" == "running" ]]; then
            log "$container is $status"
            return 0
        fi

        if (( $(date +%s) - start_ts >= timeout )); then
            log "Timed out waiting for $container to become healthy"
            return 1
        fi
        sleep 1
    done
}

# Clear SSRF listener log for a clean baseline
log "Clearing SSRF listener log..."
docker exec "$SSRF_CONTAINER" sh -c 'rm -f /app/logs/ssrf_requests.json' 2>/dev/null || true

wait_healthy "$SSRF_CONTAINER" 30
wait_healthy "$SSRF_PROXY_CONTAINER" 30

# Set up socat port forward for the TLS proxy in container emulator mode
if docker inspect "$EMULATOR_CONTAINER" >/dev/null 2>&1; then
    log "Container emulator mode detected — setting up socat for SSRF TLS proxy port ${SSRF_PORT}"
    docker exec "$EMULATOR_CONTAINER" pkill -f "socat.*TCP-LISTEN:${SSRF_PORT}" 2>/dev/null || true
    docker exec -d "$EMULATOR_CONTAINER" \
        socat "TCP-LISTEN:${SSRF_PORT},fork,reuseaddr" "TCP:${SSRF_PROXY_CONTAINER}:443"
    log "Port forward active: emulator:${SSRF_PORT} -> ${SSRF_PROXY_CONTAINER}:443"
else
    log "Native emulator mode — no socat needed (10.0.2.2 routes to host)"
fi

log "Preparation complete"
