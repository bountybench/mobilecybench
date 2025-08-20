#!/bin/bash
set -euo pipefail

ROOT_SSH_DIR="/root/.ssh"

mkdir -p "${ROOT_SSH_DIR}"
chmod 700 "${ROOT_SSH_DIR}"

check_dockerd() {
    docker info > /dev/null 2>&1
    return $?
}

echo "[entrypoint] Checking if Docker daemon is already running..."
if check_dockerd; then
    echo "[entrypoint] Docker daemon is already running, skipping startup."
else
    echo "[entrypoint] Starting Docker daemon..."
    dockerd > /var/log/dockerd.log 2>&1 &

    echo "[entrypoint] Waiting for Docker daemon to come up..."
    timeout 30 sh -c "while (! docker info > /dev/null 2>&1); do sleep 1; done"
    if [ $? -ne 0 ]; then
        echo "[entrypoint] Error: Docker daemon failed to start within 30 seconds."
        cat /var/log/dockerd.log
        exit 1
    fi
    echo "[entrypoint] Docker daemon is running."
fi

echo "[entrypoint] Starting main process: $@"
exec "$@"
