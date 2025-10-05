#!/bin/bash
# Orchestrator Container Entrypoint
# Sets up the environment for running MobileCybench experiments
# Verifies connection to host Docker daemon via socket

set -e

echo "============================================"
echo "MobileCybench Orchestrator Container"
echo "============================================"

# Check Docker connection (using host Docker socket)
echo "Checking Docker connection to host daemon..."
if docker info >/dev/null 2>&1; then
    echo "✓ Connected to host Docker daemon"
    docker --version
    echo "Docker containers running on host:"
    docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}"
else
    echo "✗ Failed to connect to Docker daemon"
    echo "Make sure the container was started with: -v /var/run/docker.sock:/var/run/docker.sock"
    exit 1
fi

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

# Display codebase status
echo ""
echo "Codebase status:"
echo "Working directory: $(pwd)"
if [ -d "/mobilecybench" ]; then
    echo "✓ /mobilecybench directory exists"
    echo "Key files:"
    ls -la /mobilecybench/*.sh 2>/dev/null | head -5 || echo "  No shell scripts found"
else
    echo "✗ /mobilecybench directory not found"
fi

echo ""
echo "============================================"
echo "Environment ready!"
echo "To run an experiment: ./docker/run_experiment.sh <app_name>"
echo "============================================"
echo ""

# Execute the command passed to docker run
exec "$@"
