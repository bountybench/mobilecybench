#!/bin/bash
# Orchestrator Container Entrypoint
# Sets up the environment for running MobileCybench experiments
# Starts Docker daemon for Docker-in-Docker

set -e

echo "============================================"
echo "MobileCybench Orchestrator Container"
echo "============================================"

# Start Docker daemon (Docker-in-Docker)
echo "Starting Docker daemon..."

# Check if dockerd is already running
if pgrep -x dockerd > /dev/null; then
    echo "✓ Docker daemon already running"
else
    # Start dockerd in background
    # Note: storage-driver is configured in /etc/docker/daemon.json, don't specify it here
    dockerd \
        --host=unix:///var/run/docker.sock \
        --host=tcp://0.0.0.0:2375 \
        > /var/log/docker.log 2>&1 &

    # Wait for Docker daemon to be ready
    echo "Waiting for Docker daemon to be ready..."
    TIMEOUT=30
    COUNT=0
    while ! docker info >/dev/null 2>&1; do
        if [ $COUNT -ge $TIMEOUT ]; then
            echo "✗ Docker daemon failed to start within ${TIMEOUT} seconds"
            echo "Check logs: /var/log/docker.log"
            tail -n 20 /var/log/docker.log
            exit 1
        fi
        sleep 1
        COUNT=$((COUNT + 1))
    done
    echo "✓ Docker daemon started successfully"
fi

# Display Docker info
docker --version
docker info | head -n 10

# Check Android SDK installation
echo "Checking Android SDK..."
if [ -d "${ANDROID_HOME}" ]; then
    echo "✓ Android SDK: ${ANDROID_HOME}"

    # Check ADB (may not work on ARM64)
    if [ -f "${ANDROID_HOME}/platform-tools/adb" ]; then
        # Check architecture - ADB is x86_64 and won't run on ARM64
        ARCH=$(uname -m)
        if [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then
            echo "  ⚠ ADB binary present but incompatible with ARM64 architecture"
        else
            # Try to get version on x86_64
            ADB_OUTPUT=$(timeout 5 ${ANDROID_HOME}/platform-tools/adb version 2>&1 || echo "failed")
            if echo "$ADB_OUTPUT" | grep -q "Android Debug Bridge"; then
                echo "  ✓ ADB: $(echo "$ADB_OUTPUT" | head -n1)"
                adb start-server 2>/dev/null || echo "  ⚠ ADB server failed to start"
            else
                echo "  ⚠ ADB binary found but cannot execute"
            fi
        fi
    else
        echo "  ✗ ADB not found"
    fi

    # Check Emulator
    if [ -d "${ANDROID_HOME}/emulator" ]; then
        if [ -f "${ANDROID_HOME}/emulator/emulator" ]; then
            EMULATOR_VERSION=$(${ANDROID_HOME}/emulator/emulator -version 2>&1 | head -n1)
            if [ $? -eq 0 ]; then
                echo "  ✓ Emulator: $EMULATOR_VERSION"
            else
                echo "  ⚠ Emulator binary found but cannot execute (likely architecture mismatch)"
            fi
        else
            echo "  ✗ Emulator binary not found"
        fi
    else
        echo "  ⚠ Emulator not installed (expected on ARM64)"
    fi
else
    echo "✗ Android SDK not found at ${ANDROID_HOME}"
fi

# Check Java installation
echo "Checking Java..."
java -version 2>&1 | head -n1 || echo "✗ Java not found"

# Check Python installation
echo "Checking Python..."
python3 --version || echo "✗ Python not found"

# Display mounted volumes
echo ""
echo "Mounted volumes:"
ls -la /mobilecybench/ | head -n 20

echo ""
echo "============================================"
echo "Environment ready. Running command: $@"
echo "============================================"
echo ""

# Execute the command passed to docker run
exec "$@"
