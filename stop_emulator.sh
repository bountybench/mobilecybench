#!/bin/bash

echo "Stopping Android emulator..."

# Graceful shutdown via ADB console
adb emu kill 2>/dev/null || true

# Wait up to 10s for the emulator process to actually exit
for i in $(seq 1 10); do
    if ! pgrep -f "emulator.*-avd" >/dev/null 2>&1; then
        echo "Emulator process terminated"
        break
    fi
    sleep 1
done

# Force-kill any remaining emulator processes
if pgrep -f "emulator.*-avd" >/dev/null 2>&1; then
    echo "Emulator did not exit gracefully, force killing..."
    pkill -f "emulator.*-avd" 2>/dev/null || true
    sleep 2
fi

# Reset ADB server to clear stale device state for the next run
echo "Resetting ADB server..."
adb kill-server 2>/dev/null || true

echo "Emulator stopped"
