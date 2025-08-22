#!/usr/bin/env bash
set -euo pipefail

# Start Docker daemon with log redirection
dockerd > /var/log/dockerd.log 2>&1 &

# Health check for Docker daemon
echo "==> Validating Docker startup..."
DOCKER_READY_MAX_RETRIES=30
DOCKER_READY_INTERVAL=1

for ((i=0; i<DOCKER_READY_MAX_RETRIES; i++)); do
  if docker info &>/dev/null; then
    echo " Docker operational after $((i+1)) seconds"
    break
  fi
  if [[ $i -eq $((DOCKER_READY_MAX_RETRIES-1)) ]]; then
    echo "!!! Docker failed to start after $DOCKER_READY_MAX_RETRIES seconds"
    exit 1
  fi
  sleep $DOCKER_READY_INTERVAL
  echo "    Waiting for Docker... ($((i+1))/$DOCKER_READY_MAX_RETRIES)"
done

# Main execution logic
if [[ $# -gt 0 ]]; then
  echo "==> Executing command: $@"
  exec "$@"
else
  echo "==> No command specified. Starting persistent shell session"
  echo "    Project directory: /mobilecybench"
  echo "    Use 'exit' to terminate container"
  exec /bin/bash -c "trap : TERM INT; sleep infinity & wait"
fi