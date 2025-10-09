#!/bin/bash
set -e

# Clean up stale Docker daemon PID file
rm -f /var/run/docker.pid

dockerd --host=unix:///var/run/docker.sock &

echo "Waiting for Docker daemon to start..."
timeout=30
while [ $timeout -gt 0 ]; do
    if docker info >/dev/null 2>&1; then
        echo "Docker daemon is ready"
        break
    fi
    sleep 1
    timeout=$((timeout - 1))
done

if [ $timeout -eq 0 ]; then
    echo "Docker daemon failed to start"
    exit 1
fi

if ! docker network inspect shared_net >/dev/null 2>&1; then
    echo "Creating shared_net network..."
    docker network create shared_net
fi

if [ -f /app/pyproject.toml ]; then
    cd /app && /opt/venv/bin/pip install --no-cache-dir -e . >/dev/null 2>&1 || true
fi

# Keep container running
exec "$@"
