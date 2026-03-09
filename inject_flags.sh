#!/bin/bash

# A wrapper script to inject or remove security flags into Android apps and Docker containers
# based on a metedata.json.

set -e # Exit immediately if a command exits with a non-zero status.
set -o pipefail # The return value of a pipeline is the status of the last command to exit with a non-zero status.

DEFAULT_APP_PATH="."

usage() {
    echo "Usage: $0 [--remove] [app_path]"
    echo "  --remove        : Removes flags instead of injecting them."
    echo "  app_path        : Path to the app. Defaults to '.'"
    exit 1
}

REMOVE_FLAG=""
APP_PATH=$DEFAULT_APP_PATH
CONFIG_FILE="metadata.json"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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
        # If it's not a flag, assume it's the app path
        if [[ -d "$arg" ]]; then
            APP_PATH="$arg"
        else
            # Allow for arguments like --other_flag that we don't handle
            # This is to avoid breaking if the script is extended later
            if [[ "$arg" == -* ]]; then
                echo "Warning: Unrecognized argument '$arg' - ignoring." >&2
            else
                echo "Warning: Dierctory '$arg' not found - ignoring." >&2
            fi
        fi
        ;;
    esac
done


if [ -d $APP_PATH ]; then
  echo "cd into app directory..."
  cd $APP_PATH
  APP_DIR="$(pwd)"
else
  echo "ERROR: app directory not found"
  exit 1
fi

# Check if jq is installed
if ! command -v jq &> /dev/null; then
    echo "Error: 'jq' is not installed. Please install it to parse the JSON config file."
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
    cd "$SCRIPT_DIR"
    python -m utils.flag_injection_utils --package "$PACKAGE_NAME" $REMOVE_FLAG
    cd "$APP_DIR"
else
    # Call python script once with all container names
    echo "$ACTION container flags for containers: $CONTAINER_NAMES"
    # The $CONTAINER_NAMES variable will be expanded by the shell into separate arguments
    cd "$SCRIPT_DIR"
    python -m utils.flag_injection_utils --package "$PACKAGE_NAME" --containers $CONTAINER_NAMES $REMOVE_FLAG
    cd "$APP_DIR"
    echo "--------------------------------------------------"
fi


# Clear any activity_flag.txt created by VulnFlagActivity during app launch.
# This must happen as the LAST step — after all flag injections and their
# adb root/unroot cycles — because each adbd restart can trigger Android
# to restore VulnFlagActivity's singleInstance task, recreating the file.
# We intentionally leave adbd rooted so the next _ensure_root() call (in
# the generic probe) is a no-op and doesn't restart adbd again.
if [[ -z "$REMOVE_FLAG" ]]; then
    echo "Clearing baseline activity_flag.txt..."
    adb root 2>&1 || true
    adb wait-for-device
    # Wait for shell to become responsive after potential adbd restart
    for _i in $(seq 1 30); do
        adb shell true 2>/dev/null && break
        sleep 0.5
    done
    sleep 2
    FLAG_FILE="/data/data/$PACKAGE_NAME/files/activity_flag.txt"
    # Retry loop: force-stop + delete, then verify. VulnFlagActivity may be
    # restored asynchronously after adbd restart, so we may need multiple passes.
    for _attempt in 1 2 3; do
        adb shell "am force-stop $PACKAGE_NAME" 2>/dev/null || true
        sleep 1
        adb shell "rm -f $FLAG_FILE" 2>/dev/null || true
        _check=$(adb shell "test -f $FLAG_FILE && echo FOUND || echo NOTFOUND" 2>/dev/null)
        if echo "$_check" | grep -q "NOTFOUND"; then
            echo "activity_flag.txt cleared (attempt $_attempt)"
            break
        fi
        echo "activity_flag.txt still exists after attempt $_attempt, retrying..."
        sleep 2
    done
fi

echo "Script finished."
