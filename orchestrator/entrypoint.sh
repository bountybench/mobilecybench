#!/bin/bash
set -e

# Clean up stale Docker daemon PID file
rm -f /var/run/docker.pid

# Use explicit DNS servers to prevent the Android emulator's virtual DNS
# (10.0.2.3) from polluting the DinD daemon's resolver. Without this,
# image pulls and builds fail after the emulator container starts.
dockerd --host=unix:///var/run/docker.sock --dns 8.8.8.8 --dns 8.8.4.4 &

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

# Docker Hub auth (optional — avoids rate limits on image pulls)
if [ -n "${DOCKERHUB_USERNAME:-}" ] && [ -n "${DOCKERHUB_TOKEN:-}" ]; then
    echo "$DOCKERHUB_TOKEN" | docker login -u "$DOCKERHUB_USERNAME" --password-stdin
    echo "Docker Hub login successful"
fi

if ! docker network inspect shared_net >/dev/null 2>&1; then
    echo "Creating shared_net network..."
    docker network create shared_net
fi

if [ -f /mobilecybench/pyproject.toml ]; then
    cd /mobilecybench && /opt/venv/bin/pip install --no-cache-dir -e . >/dev/null 2>&1 || true
fi

# Start ADB on all interfaces (-a) so agent containers can reach it
# via host.docker.internal:5037. Without -a, ADB binds to 127.0.0.1
# only, which is unreachable from the docker0 bridge on Linux.
# See issue #688.
echo "Starting ADB server on all interfaces..."
adb -a start-server

# If APP_NAME is provided, run the runner
if [ -n "$APP_NAME" ]; then
    echo "Running MobileCybench for app: $APP_NAME"
    cd /mobilecybench

    # Ensure headless display in runner_config.json (orchestrator runs without display)
    # This changes the host filesystem via volume mount
    if [ -f runner_config.json ]; then
        jq '.emulator_display = "headless"' runner_config.json > runner_config.json.tmp && mv runner_config.json.tmp runner_config.json
        echo "Set emulator_display=headless in runner_config.json"
    fi

    python3 runner.py "$APP_NAME"
fi

# Keep container running
exec "$@"
