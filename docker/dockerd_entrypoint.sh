#!/bin/bash
set -e

# This script starts dockerd in the background for Docker-in-Docker support
# and then runs the main entrypoint

echo "=== Starting Docker daemon for DinD support ==="

# Check if running with --privileged flag
if [ ! -w /sys/fs/cgroup ]; then
    echo "WARNING: Container is not running in privileged mode."
    echo "Docker-in-Docker may not work properly."
    echo "Run with: docker run --privileged ..."
fi

# Start Docker daemon in the background if not already running
if ! docker info >/dev/null 2>&1; then
    echo "Starting Docker daemon..."

    # Create docker directories
    mkdir -p /var/lib/docker /var/run

    # Start dockerd with appropriate settings
    dockerd \
        --host=unix:///var/run/docker.sock \
        --storage-driver=overlay2 \
        --log-level=error \
        > /var/log/dockerd.log 2>&1 &

    # Wait for Docker to be ready
    echo "Waiting for Docker daemon to start..."
    timeout=30
    elapsed=0
    while [ $elapsed -lt $timeout ]; do
        if docker info >/dev/null 2>&1; then
            echo "Docker daemon started successfully"
            break
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done

    if [ $elapsed -eq $timeout ]; then
        echo "WARNING: Docker daemon failed to start within timeout"
        echo "Container will continue but Docker-in-Docker features will not work"
    fi
else
    echo "Docker daemon is already running"
fi

# Execute the main entrypoint
echo "Executing main entrypoint..."
exec /usr/local/bin/entrypoint.sh "$@"