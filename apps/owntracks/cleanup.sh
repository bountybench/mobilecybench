#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

echo "Cleaning up OwnTracks environment..."

RUNTIME_DIR="${MCB_OWNTRACKS_RUNTIME_DIR:-${TMPDIR:-/tmp}/mobilecybench-owntracks-runtime}"
LEGACY_RUNTIME_DIR="${TMPDIR:-/tmp}/mobilecybench-owntracks-runtime"
MOSQUITTO_RUNTIME_DIR="$RUNTIME_DIR/mosquitto-config"
LEGACY_EVIDENCE_DIR="${TMPDIR:-/tmp}/mobilecybench-owntracks-evidence"

if command -v docker >/dev/null 2>&1; then
    MCB_MOSQUITTO_RUNTIME_DIR="$MOSQUITTO_RUNTIME_DIR" \
        docker compose down --remove-orphans >/dev/null 2>&1 || true
    docker rm -f mosquitto >/dev/null 2>&1 || true
fi

rm -f "mosquitto/config/runtime.env" "mosquitto/config/mosquitto.password"
rm -rf "$RUNTIME_DIR" "$LEGACY_RUNTIME_DIR" "$LEGACY_EVIDENCE_DIR"

echo "Cleanup complete."
