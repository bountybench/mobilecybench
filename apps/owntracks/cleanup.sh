#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

echo "Cleaning up OwnTracks environment..."

if command -v docker >/dev/null 2>&1; then
    docker compose down --remove-orphans >/dev/null 2>&1 || true
    docker rm -f mosquitto >/dev/null 2>&1 || true
fi

rm -rf "${TMPDIR:-/tmp}/mobilecybench-owntracks-runtime"

echo "Cleanup complete."
