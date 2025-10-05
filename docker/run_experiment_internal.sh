#!/bin/bash
# Run an experiment from within the backend container
# This script should be executed INSIDE the mobilecybench-backend container
# Usage: ./docker/run_experiment.sh <app_name> [config_file]

set -e

if [ $# -lt 1 ]; then
    echo "Usage: $0 <app_name> [config_file]"
    echo ""
    echo "Example:"
    echo "  $0 owncloud-android"
    echo "  $0 owncloud-android custom_config.json"
    echo ""
    echo "Note: Run this script from INSIDE the backend container"
    exit 1
fi

APP_NAME="$1"
CONFIG_FILE="${2:-runner_config.json}"

echo "============================================"
echo "Running experiment for: $APP_NAME"
echo "Config file: $CONFIG_FILE"
echo "============================================"
echo ""

# Verify we're inside the backend container
if [ ! -f "/mobilecybench/setup.sh" ]; then
    echo "Error: This script must be run from inside the backend container"
    echo "Expected to find /mobilecybench/setup.sh"
    exit 1
fi

# Change to the mobilecybench directory
cd /mobilecybench

# Run the experiment
echo "Setting up app backend and emulator for $APP_NAME..."
./setup.sh "$APP_NAME"

echo ""
echo "Starting emulator..."
./start_emulator.sh --yes

echo ""
echo "Running experiment..."
python3 runner.py "$APP_NAME" "$CONFIG_FILE"

echo ""
echo "============================================"
echo "Experiment complete!"
echo "============================================"
echo ""
echo "Results are saved in the /mobilecybench/results directory"
echo "Logs are saved in the /mobilecybench/logs directory"
echo ""
