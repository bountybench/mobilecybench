#!/bin/bash
# Start Xvfb (X Virtual FrameBuffer) for headless emulator
# This creates a virtual display that the emulator can use without a physical screen

set -e

echo "Starting Xvfb on display :0..."

# Kill any existing Xvfb on display :0
pkill -f "Xvfb :0" || true
sleep 1

# Start Xvfb in background
# Resolution: 1280x720 with 24-bit color depth
Xvfb :0 -screen 0 1280x720x24 -nolisten tcp -nolisten unix &

# Wait for Xvfb to be ready
sleep 2

# Verify Xvfb is running
if pgrep -f "Xvfb :0" > /dev/null; then
    echo "✓ Xvfb started successfully on display :0"
else
    echo "✗ Failed to start Xvfb"
    exit 1
fi

# Start fluxbox window manager
DISPLAY=:0 fluxbox &

echo "✓ Virtual display ready for emulator"
