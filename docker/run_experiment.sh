#!/bin/bash
# Run an experiment inside the orchestrator container
# Usage: ./docker/run_experiment.sh <app_name> [config_file]

set -e

if [ $# -lt 1 ]; then
    echo "Usage: $0 <app_name> [config_file]"
    echo ""
    echo "Example:"
    echo "  $0 owncloud-android"
    echo "  $0 owncloud-android custom_config.json"
    exit 1
fi

APP_NAME="$1"
CONFIG_FILE="${2:-runner_config.json}"

CONTAINER_NAME="mobilecybench-orchestrator"

echo "============================================"
echo "Running experiment for: $APP_NAME"
echo "Config file: $CONFIG_FILE"
echo "============================================"
echo ""

# Check if container is running
if ! docker ps | grep -q "$CONTAINER_NAME"; then
    echo "Error: Orchestrator container is not running."
    echo "Start it with: ./docker/start_orchestrator.sh"
    exit 1
fi

# Run the experiment inside the container
echo "Setting up emulator for $APP_NAME..."
docker exec -it "$CONTAINER_NAME" bash -c "./setup.sh $APP_NAME"

echo ""
echo "Starting emulator..."
docker exec -it "$CONTAINER_NAME" bash -c "./start_emulator.sh --yes"

echo ""
echo "Running experiment..."
docker exec -it "$CONTAINER_NAME" bash -c "python3 runner.py $APP_NAME $CONFIG_FILE"

echo ""
echo "============================================"
echo "Experiment complete!"
echo "============================================"
echo ""
echo "Results are saved in the ./results directory"
echo "Logs are saved in the ./logs directory"
echo ""
