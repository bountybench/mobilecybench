#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Removing scores..."
rm -f scores.json

echo "Clearing ADB logs..."
if command -v adb >/dev/null 2>&1 && adb get-state >/dev/null 2>&1; then
    adb logcat -c 2>/dev/null || true
fi

echo "Removing log files..."
rm -f fake_agent_log.log
rm -f *.log

echo "Taking down containers..."
if docker info >/dev/null 2>&1; then
    docker compose down -v --remove-orphans 2>/dev/null || true
fi

echo "Cleanup complete"
