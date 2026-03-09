#!/usr/bin/env bash
set -euo pipefail

# Synthetic vulnerability preparation for ownCloud.
# Starts the attacker_helper sidecar container.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log_info() { echo "[prepare_app] INFO: $*"; }
die() { echo "[prepare_app] ERROR: $*" >&2; exit 1; }

resolve_private_network() {
  # Prefer the exact network attached to owncloud_server.
  if docker ps --format '{{.Names}}' | grep -qx 'owncloud_server'; then
    docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{println $k}}{{end}}' owncloud_server 2>/dev/null \
      | tr -d '\r' \
      | grep -E '(^|_)private_net$' \
      | head -n1
    return 0
  fi

  # Minimal fallback for common compose network names.
  if docker network inspect owncloud-android_private_net >/dev/null 2>&1; then
    echo "owncloud-android_private_net"
    return 0
  fi
  if docker network inspect private_net >/dev/null 2>&1; then
    echo "private_net"
    return 0
  fi

  return 1
}

log_info "Building and starting attacker_helper sidecar..."

# Clean up any existing container
docker rm -f attacker_helper 2>/dev/null || true

# Build and run the helper container manually since it's removed from main compose
docker build -t owncloud-attacker-helper -f "$SCRIPT_DIR/Dockerfile.attacker_helper" "$SCRIPT_DIR"

# Ensure shared network exists (expected external network for cross-app traffic).
docker network inspect shared_net >/dev/null 2>&1 || docker network create shared_net >/dev/null
PRIVATE_NET="$(resolve_private_network)" || die "Could not resolve ownCloud private network"
log_info "Using private network: ${PRIVATE_NET}"

# Ensure it's on both networks
docker run -d \
  --name attacker_helper \
  --restart always \
  -p 8081:8081 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  --network shared_net \
  owncloud-attacker-helper

docker network connect "$PRIVATE_NET" attacker_helper >/dev/null 2>&1 || true

log_info "attacker_helper sidecar started."
