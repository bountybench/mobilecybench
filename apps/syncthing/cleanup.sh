#!/bin/bash
set -e

echo "Removing scores..."
rm -f scores.json

echo "Clearing ADB logs..."
adb logcat -c 2>/dev/null || true

echo "Removing log files..."
rm -f fake_agent_log.log
rm -f *.log

echo "Cleanup complete"
