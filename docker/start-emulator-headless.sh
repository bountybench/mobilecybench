#!/bin/bash
# Start Android emulator in headless mode with VNC access
# This script orchestrates Xvfb, VNC, and the emulator itself

set -e

AVD_NAME="${1:-test_avd}"

echo "============================================"
echo "Starting Headless Android Emulator"
echo "AVD: $AVD_NAME"
echo "============================================"

# 1. Start Xvfb (virtual display)
echo ""
echo "[1/4] Starting virtual display (Xvfb)..."
/usr/local/bin/start-xvfb.sh

# 2. Start VNC server
echo ""
echo "[2/4] Starting VNC server..."
/usr/local/bin/start-vnc.sh

# 3. Start ADB server
echo ""
echo "[3/4] Starting ADB server..."
adb start-server 2>/dev/null || echo "ADB server already running or failed to start"

# 4. Start emulator
echo ""
echo "[4/4] Starting Android emulator..."
echo "  AVD: $AVD_NAME"
echo "  Display: $DISPLAY"
echo ""

# Check if AVD exists
if ! ${ANDROID_HOME}/cmdline-tools/latest/bin/avdmanager list avd | grep -q "Name: $AVD_NAME"; then
    echo "✗ AVD '$AVD_NAME' not found!"
    echo "Available AVDs:"
    ${ANDROID_HOME}/cmdline-tools/latest/bin/avdmanager list avd
    echo ""
    echo "Create an AVD first with: ./setup.sh <app_name>"
    exit 1
fi

# Start emulator in background
# -no-window: Don't show emulator window (use VNC instead)
# -no-audio: Disable audio
# -gpu swiftshader_indirect: Software rendering (compatible with Docker)
# -no-snapshot: Don't save/restore state
# -wipe-data: Start fresh (optional, remove if you want persistence)
DISPLAY=:0 ${ANDROID_HOME}/emulator/emulator \
    -avd "$AVD_NAME" \
    -no-window \
    -no-audio \
    -gpu swiftshader_indirect \
    -no-snapshot \
    -no-boot-anim \
    &

EMULATOR_PID=$!

echo "✓ Emulator started (PID: $EMULATOR_PID)"
echo ""
echo "============================================"
echo "Waiting for emulator to boot..."
echo "This may take 2-5 minutes..."
echo "============================================"
echo ""

# Wait for emulator to boot
timeout 300 adb wait-for-device

echo "✓ Emulator device detected!"
echo ""
echo "Waiting for boot to complete..."

# Wait for boot to complete
timeout 300 bash -c 'until adb shell getprop sys.boot_completed | grep -q 1; do sleep 2; done'

echo ""
echo "============================================"
echo "✓ Emulator is ready!"
echo "============================================"
echo ""
echo "Access options:"
echo "  • VNC: vnc://localhost:5900"
echo "  • ADB: adb devices"
echo ""
echo "Emulator logs: /var/log/emulator.log"
echo ""

# Keep script running to monitor emulator
wait $EMULATOR_PID
