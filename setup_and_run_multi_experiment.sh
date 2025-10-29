#!/usr/bin/env bash
set -euo pipefail

# Bare-bones helper: create test containers for experiments, then run the routing test.
# Containers are lightweight Debian shells that stay alive; sufficient for echo commands.

APPS=("simplelogin" "bitwarden" "joplin")
IMAGE="debian:bookworm-slim"

echo "[setup] Pulling base image: ${IMAGE}"
docker pull "${IMAGE}" >/dev/null

for app in "${APPS[@]}"; do
  name="kali-container-${app}"
  if docker ps -a --format '{{.Names}}' | grep -q "^${name}$"; then
    status=$(docker inspect -f '{{.State.Status}}' "${name}") || status="unknown"
    if [ "${status}" != "running" ]; then
      echo "[setup] Starting existing container: ${name}"
      docker start "${name}" >/dev/null
    else
      echo "[setup] Already running: ${name}"
    fi
  else
    echo "[setup] Creating container: ${name}"
    docker run -d --name "${name}" "${IMAGE}" sleep infinity >/dev/null
  fi
done

echo "[run] Executing routing test"
python3 test_multi_experiment.py


