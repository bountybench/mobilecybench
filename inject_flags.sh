#!/bin/bash

# A wrapper script to inject or remove security flags into Android apps and Docker containers
# based on a metedata.json.

set -e # Exit immediately if a command exits with a non-zero status.
set -o pipefail # The return value of a pipeline is the status of the last command to exit with a non-zero status.

PYTHON_SCRIPT_NAME="../../utils/flag_injection_utils.py"
DEFAULT_CONFIG_FILE="metadata.json"

usage() {
    echo "Usage: $0 [--remove] [config_file.json]"
    echo "  --remove        : Removes flags instead of injecting them."
    echo "  config_file.json: Path to the JSON config file. Defaults to 'config.json'."
    exit 1
}

REMOVE_FLAG=""
CONFIG_FILE=$DEFAULT_CONFIG_FILE

# Process command-line arguments
for arg in "$@"; do
    case $arg in
        --remove)
        REMOVE_FLAG="--remove"
        shift # Remove --remove from processing
        ;;
        -h|--help)
        usage
        ;;
        *)
        # If it's not a flag, assume it's the config file path
        if [[ -f "$arg" ]]; then
            CONFIG_FILE="$arg"
        else
            # Allow for arguments like --other_flag that we don't handle
            # This is to avoid breaking if the script is extended later
            if [[ "$arg" == -* ]]; then
                echo "Warning: Unrecognized argument '$arg' - ignoring." >&2
            else
                echo "Warning: File '$arg' not found - ignoring." >&2
            fi
        fi
        ;;
    esac
done


# Check if config file exists
if [ ! -f "$CONFIG_FILE" ]; then
    echo "Error: Configuration file '$CONFIG_FILE' not found."
    usage
fi

# Check if jq is installed
if ! command -v jq &> /dev/null; then
    echo "Error: 'jq' is not installed. Please install it to parse the JSON config file."
    exit 1
fi

# Check if the python script exists
if [ ! -f "$PYTHON_SCRIPT_NAME" ]; then
    echo "Error: Python script '$PYTHON_SCRIPT_NAME' not found in the current directory."
    exit 1
fi


# --- Main Logic ---
echo "Reading configuration from: $CONFIG_FILE"

# Extract data using jq. The -r flag removes quotes from the output.
PACKAGE_NAME=$(jq -r '.package_name' "$CONFIG_FILE")
# Read all container names into a space-separated string
CONTAINER_NAMES=$(jq -r '.container_names[]' "$CONFIG_FILE" | xargs)

# Validate extracted data
if [[ -z "$PACKAGE_NAME" || "$PACKAGE_NAME" == "null" ]]; then
    echo "Error: 'package_name' not found or is null in $CONFIG_FILE."
    exit 1
fi

ACTION="Injecting"
if [[ "$REMOVE_FLAG" == "--remove" ]]; then
    ACTION="Removing"
fi

echo "--------------------------------------------------"
echo "$ACTION Android flag for package: $PACKAGE_NAME"
echo "--------------------------------------------------"


if [[ -z "$CONTAINER_NAMES" ]]; then
    echo "No 'container_names' found in config. Nothing to do for containers."
    python "$PYTHON_SCRIPT_NAME" --package "$PACKAGE_NAME" $REMOVE_FLAG
else
    # Call python script once with all container names
    echo "$ACTION container flags for containers: $CONTAINER_NAMES"
    # The $CONTAINER_NAMES variable will be expanded by the shell into separate arguments
    python "$PYTHON_SCRIPT_NAME" --package "$PACKAGE_NAME" --container $CONTAINER_NAMES $REMOVE_FLAG
    echo "--------------------------------------------------"
fi


echo "Script finished."
