#!/bin/bash
set -e

echo "Removing scores..."
rm -f scores.json

echo "Clearing ADB logs..."
timeout 5 adb logcat -c 2>/dev/null || true 2>/dev/null || true

echo "Removing log files..."
rm -f fake_agent_log.log
rm -f *.log
rm -f .runtime_integrity_state.json

echo "Removing per-run probe nonce artifacts..."
rm -f .b9_hidden_jid .app_pid_baseline

echo "Taking down containers..."
docker compose down -v

echo "Cleanup complete"