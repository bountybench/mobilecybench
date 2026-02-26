#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cd "${SCRIPT_DIR}"

echo "Stopping Radicale container"

docker compose down

# Remove Radicale data directory created at runtime.
# Files are owned by the container UID, so use docker to delete them
# when a normal rm fails. Cleanup failures are non-fatal.
if [ -d "$SCRIPT_DIR/radicale/data" ]; then
  echo "Removing radicale/data/"
  rm -rf "$SCRIPT_DIR/radicale/data" 2>/dev/null \
    || docker run --rm -v "$SCRIPT_DIR/radicale/data:/data" alpine rm -rf /data/* 2>/dev/null \
    || echo "Warning: could not fully remove radicale/data/ (permission denied); continuing anyway"
fi