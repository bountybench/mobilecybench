#!/bin/bash
# Simplified experiment runner that skips SDK setup if it fails
# This allows running the Python tests directly

APP_NAME="${1:-audiobookshelf}"
CONFIG_FILE="${2:-runner_config.json}"

echo "============================================"
echo "Simplified Experiment Runner"
echo "Running experiment for: $APP_NAME"
echo "Config file: $CONFIG_FILE"
echo "============================================"
echo ""

cd /mobilecybench

# Check if Python and requirements are available
echo "Checking Python environment..."
python3 --version

# Run the runner.py directly
echo "Running experiment with runner.py..."
echo ""

# The runner.py will handle the Android setup internally
# or skip it if not needed for the specific tests
python3 runner.py "$APP_NAME" "$CONFIG_FILE" 2>&1

echo ""
echo "============================================"
echo "Experiment complete!"
echo "Results are in /mobilecybench/results/"
echo "Logs are in /mobilecybench/logs/"
echo "============================================"