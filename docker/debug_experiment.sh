#!/bin/bash
# Debug version of run_experiment_internal.sh
# Runs without set -e to see all output

APP_NAME="$1"
CONFIG_FILE="${2:-runner_config.json}"

echo "============================================"
echo "Running experiment for: $APP_NAME"
echo "Config file: $CONFIG_FILE"
echo "============================================"
echo ""

cd /mobilecybench

echo "Step 1: Running setup.sh..."
./setup.sh "$APP_NAME"
echo "Setup.sh exit code: $?"
echo ""

echo "Step 2: Starting emulator..."
./start_emulator.sh --yes
echo "start_emulator.sh exit code: $?"
echo ""

echo "Step 3: Running experiment..."
python3 runner.py "$APP_NAME" "$CONFIG_FILE"
echo "runner.py exit code: $?"
echo ""

echo "============================================"
echo "Experiment complete!"
echo "============================================"