#!/bin/bash
# Start VNC server for remote access to emulator display
# This allows you to connect to the emulator GUI via VNC client

set -e

echo "Starting VNC server..."

# Kill any existing x11vnc
pkill x11vnc || true
sleep 1

# Start x11vnc on port 5900
# -display :0 - Connect to Xvfb display
# -forever - Keep running after client disconnects
# -shared - Allow multiple clients
# -nopw - No password (change this in production!)
x11vnc -display :0 -forever -shared -nopw -rfbport 5900 &

# Wait for VNC to be ready
sleep 2

# Verify VNC is running
if pgrep x11vnc > /dev/null; then
    echo "✓ VNC server started on port 5900"
    echo "  Connect with: vnc://localhost:5900"
else
    echo "✗ Failed to start VNC server"
    exit 1
fi
