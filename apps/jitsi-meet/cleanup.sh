#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -d jitsi-docker/jitsi-latest ]; then
    cd jitsi-docker/jitsi-latest
    echo "Removing Docker containers..."
    docker compose down -v 2>/dev/null || true
    cd ../..
else
    echo "jitsi-docker/jitsi-latest not found, skipping container cleanup"
fi

echo "Cleaning up docker volumes..."
docker volume prune -f

echo "Removing generated files..."
rm -f scores.json current_state.json agent.log prosody.hash

# Verifier-owned baselines written by capture_verifier_baseline.py during
# start_runtime.sh. Stale baselines from an earlier run can mismatch a fresh
# emulator + docker stack (e.g. RKStorage default rows differ across SDK
# versions, container PIDs change, logcat fence uuids no longer present in
# the live ring buffer), causing probes to either false-fire or SKIP for the
# wrong reason. Wipe between experiments; start_runtime.sh re-captures.
if [ -d verifier_artifacts ]; then
    echo "Removing stale verifier_artifacts/ baselines..."
    rm -rf verifier_artifacts
fi

echo "Removing python attacker server if it exists"
if [ -f /tmp/attacker_server.pid ]; then
    kill $(cat /tmp/attacker_server.pid) 2>/dev/null || true
    rm /tmp/attacker_server.pid
    echo "Attacker server stopped"
else
    # Fallback: kill by port in case pid file is missing
    fuser -k 5000/tcp 2>/dev/null || true
fi

echo "Removing Jitsi GIF canary server if it exists"
docker rm -f jitsi-gif-canary >/dev/null 2>&1 || true
if docker inspect emulator-container >/dev/null 2>&1; then
    docker exec emulator-container pkill -f "socat.*TCP-LISTEN:18765" 2>/dev/null || true
fi
rm -rf /tmp/jitsi_gif_canary_secure /tmp/jitsi_gif_canary_vulnerable /tmp/jitsi_gif_canary_phase 2>/dev/null || true

echo "Cleanup complete."
