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
if ! docker network inspect adb_net >/dev/null 2>&1; then
    echo "Creating adb_net network..."
    docker network create --driver bridge adb_net
fi

echo "Building ADB server image..."
docker build -t mobilecybench/adb-server:latest -f /mobilecybench/utils/Dockerfile.adb-server /mobilecybench/utils/

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
