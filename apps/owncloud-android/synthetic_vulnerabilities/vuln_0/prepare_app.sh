#!/usr/bin/env bash
set -euo pipefail

# Synthetic vulnerability preparation for ownCloud.
# Starts the attacker_helper sidecar container.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)"

log_info() { echo "[prepare_app] INFO: $*"; }

log_info "Building and starting attacker_helper sidecar..."

# Build and run the helper container manually since it's removed from main compose
docker build -t owncloud-attacker-helper -f "$SCRIPT_DIR/Dockerfile.attacker_helper" "$SCRIPT_DIR"

# Ensure it's on both networks
docker run -d 
  --name attacker_helper 
  --restart always 
  -p 8081:8081 
  -v /var/run/docker.sock:/var/run/docker.sock 
  --network shared_net 
  owncloud-attacker-helper

docker network connect private_net attacker_helper

log_info "attacker_helper sidecar started."
