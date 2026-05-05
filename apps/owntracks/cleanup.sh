#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

echo "Cleaning up OwnTracks environment..."

if command -v docker >/dev/null 2>&1; then
    MCB_MOSQUITTO_RUNTIME_DIR="${TMPDIR:-/tmp}/mobilecybench-owntracks-runtime/mosquitto-config" \
        docker compose down --remove-orphans >/dev/null 2>&1 || true
    docker rm -f mosquitto >/dev/null 2>&1 || true
fi

rm -f "mosquitto/config/runtime.env" "mosquitto/config/mosquitto.password"
rm -rf "${TMPDIR:-/tmp}/mobilecybench-owntracks-runtime"

echo "Cleanup complete."
