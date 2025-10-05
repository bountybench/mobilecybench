#!/bin/bash
# Setup script for ARM64 (Apple Silicon) environments
# This handles the special requirements for running on ARM64

set -e

echo "============================================"
echo "ARM64 Setup for MobileCybench"
echo "============================================"
echo ""

# Detect architecture
ARCH=$(uname -m)
if [ "$ARCH" != "aarch64" ] && [ "$ARCH" != "arm64" ]; then
    echo "This script is for ARM64 only. Detected: $ARCH"
    exit 1
fi

echo "Detected ARM64 architecture"
echo ""

# Setup environment
export ANDROID_HOME=/root/.android-sdk
export ANDROID_SDK_ROOT=/root/.android-sdk
export PATH=$PATH:$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools

# Install SDK components (without emulator which isn't available for ARM64 Linux)
echo "Installing Android SDK components for ARM64..."
yes | sdkmanager --licenses >/dev/null 2>&1 || true

# Install basic packages
sdkmanager "platform-tools" >/dev/null || echo "platform-tools installation failed"
sdkmanager "platforms;android-35" >/dev/null || echo "platforms installation failed"
sdkmanager "build-tools;34.0.0" >/dev/null || echo "build-tools installation failed"

echo ""
echo "NOTE: Android emulator is not available for ARM64 Linux."
echo "You have two options:"
echo "1. Use the host Android emulator via the bridge (requires host setup)"
echo "2. Use a physical device connected via ADB"
echo ""

# Check if ADB shim is installed
if [ -f "/usr/local/bin/adb" ]; then
    echo "✓ ADB shim is installed"
else
    echo "✗ ADB shim is missing - bridge communication will fail"
    echo "  Run: docker compose build orchestrator to fix"
fi

# Check bridge connectivity
if command -v curl >/dev/null 2>&1; then
    echo ""
    echo "Checking host bridge connectivity..."
    if curl -s "http://host.docker.internal:52888/health" >/dev/null 2>&1; then
        echo "✓ Host bridge is accessible"
    else
        echo "✗ Host bridge is not accessible at port 52888"
        echo "  Make sure the bridge is running on the host"
    fi
fi

echo ""
echo "Setup complete for ARM64!"
echo ""
echo "To run experiments without emulator:"
echo "1. Connect a physical device via ADB"
echo "2. Or ensure host emulator is running with bridge"
echo ""