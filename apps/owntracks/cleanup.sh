#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

echo "Cleaning up OwnTracks environment..."

RUNTIME_DIR="${MCB_OWNTRACKS_RUNTIME_DIR:-${RUNNER_TEMP:-${TMPDIR:-/tmp}}/owntracks-runtime}"
LEGACY_RUNTIME_DIR="${TMPDIR:-/tmp}/mobilecybench-owntracks-runtime"
MOSQUITTO_RUNTIME_DIR="$RUNTIME_DIR/mosquitto-config"
LEGACY_EVIDENCE_DIR="${TMPDIR:-/tmp}/mobilecybench-owntracks-evidence"

if command -v docker >/dev/null 2>&1; then
    MCB_MOSQUITTO_CONTAINER_NAME="${MCB_MOSQUITTO_CONTAINER_NAME:-mosquitto}"
    OWNTRACKS_COMPOSE_PROJECT="${MCB_OWNTRACKS_COMPOSE_PROJECT:-owntracks-$(RUNTIME_DIR="$RUNTIME_DIR" python3 - <<'PY'
import hashlib
import os

print(hashlib.sha256(os.environ["RUNTIME_DIR"].encode("utf-8")).hexdigest()[:12])
PY
)}"
    MCB_MOSQUITTO_RUNTIME_DIR="$MOSQUITTO_RUNTIME_DIR" \
        MCB_MOSQUITTO_CONTAINER_NAME="$MCB_MOSQUITTO_CONTAINER_NAME" \
        MCB_MOSQUITTO_IMAGE="eclipse-mosquitto:2.0.15" \
        MCB_MOSQUITTO_HOST_PORT="${MCB_MOSQUITTO_HOST_PORT:-1883}" \
        MCB_MOSQUITTO_UID="$(id -u)" \
        MCB_MOSQUITTO_GID="$(id -g)" \
        COMPOSE_PROJECT_NAME="$OWNTRACKS_COMPOSE_PROJECT" \
        docker compose down --remove-orphans >/dev/null 2>&1 || true
    docker rm -f "$MCB_MOSQUITTO_CONTAINER_NAME" >/dev/null 2>&1 || true
fi

rm -f "mosquitto/config/runtime.env" \
    "mosquitto/config/mosquitto.password" \
    "mosquitto/config/mosquitto.acl"
rm -rf "$RUNTIME_DIR" "$LEGACY_RUNTIME_DIR" "$LEGACY_EVIDENCE_DIR" "$MOSQUITTO_RUNTIME_DIR"

echo "Cleanup complete."
