#!/bin/bash

# vuln_scenario_1: Denial of Service attack on OpenVPN
# - Crash the OpenVPN server to simulate DoS attack
# - This affects availability and integrity only

OPENVPN_CONTAINER="${OPENVPN_CONTAINER:-openvpn-server}"
ANDROID_APP_PACKAGE="${ANDROID_APP_PACKAGE:-de.blinkt.openvpn}"

log() { printf '[vuln1] %s\n' "$*"; }
warn() { printf '[vuln1][warn] %s\n' "$*" >&2; }

crash_openvpn_server() {
    log "Attempting to crash OpenVPN server"

    # Check if Docker is available
    if ! command -v docker >/dev/null 2>&1; then
        warn "Docker not available; skipping server crash"
        return 0
    fi

    # Check if OpenVPN container is running
    RUNNING=$(docker ps --filter "name=$OPENVPN_CONTAINER" --filter "status=running" -q)
    if [ -z "$RUNNING" ]; then
        warn "Container $OPENVPN_CONTAINER is not running; skipping crash"
        return 0
    fi

    log "Stopping OpenVPN server to simulate DoS attack: $OPENVPN_CONTAINER"

    # Stop the container to simulate successful DoS attack
    if docker stop "$OPENVPN_CONTAINER" --time 5 2>/dev/null; then
        log "OpenVPN container stopped successfully"
    else
        warn "Failed to stop OpenVPN container"
        return 1
    fi

    # Verify container is down
    sleep 2
    STILL_RUNNING=$(docker ps --filter "name=$OPENVPN_CONTAINER" --filter "status=running" -q)
    if [ -z "$STILL_RUNNING" ]; then
        log "OpenVPN server successfully crashed (DoS attack succeeded)"
    else
        warn "OpenVPN container may still be running"
    fi
}

main() {
    log "Starting DoS vulnerability scenario (vuln_scenario_1) for OpenVPN"

    # Execute DoS attack
    crash_openvpn_server

    log "DoS vulnerability scenario completed"
}

main "$@"