#!/bin/bash

# Clean up any existing X server locks
rm -f /tmp/.X99-lock

export DISPLAY=:99

# Start Xvfb in the background
Xvfb :99 -screen 0 1280x800x16 &
XVFB_PID=$!
sleep 3

# Start Ghidra in the background
echo "Starting Ghidra..."
/opt/ghidra/ghidraRun &
GHIDRA_PID=$!
sleep 10

# Start the MCP bridge with SSE transport
echo "Starting MCP bridge on port 9000..."
cd /opt/ghidra/Ghidra/Extensions/GhidraMCP
python3 bridge_mcp_ghidra.py --transport sse --mcp-host 0.0.0.0 --mcp-port 9000

# Cleanup on exit
kill $GHIDRA_PID $XVFB_PID 2>/dev/null