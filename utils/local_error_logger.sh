#!/bin/bash

# ANSI color codes
RED="\033[91m"
RESET="\033[0m"
ERROR="${RED}[ERROR]${RESET}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

# Error buffer configuration
ERROR_LOG_FILE="$ROOT_DIR/local_ci_errors.log"
ERROR_COUNT=0
> "$ERROR_LOG_FILE"

strip_colors() {
    sed 's/\x1b\[[0-9;]*m//g' | sed 's/\[91m//g' | sed 's/\[0m//g' | sed 's/\[ERROR\]//g'
}

# point fd 3 to stderr so we can capture errors
exec 3>&2

# redirect stderr to both fd3 and log file, but log file 
exec 2> >(tee "$ERROR_LOG_FILE" >&3 >&2)

# Function to display all buffered errors
display_error_summary() {
    # Count lines in error log
    if [ -f "$ERROR_LOG_FILE" ]; then
        ERROR_COUNT=$(grep -c . "$ERROR_LOG_FILE" 2>/dev/null || echo 0)
    fi
    
    if [ ${ERROR_COUNT} -gt 0 ]; then
        echo -e "\n${RED}=== Error Summary ===${RESET}" >&3
        echo -e "${RED}Total errors encountered: ${ERROR_COUNT}${RESET}" >&3
        echo "" >&3
        cat "$ERROR_LOG_FILE" >&3
        echo -e "${RED}=====================${RESET}\n" >&3
    fi
}

cleanup_monitor() {
    local exit_code=$?
    
    # Wait for tee to finish
    sleep 0.1
    
    # Display summary only on error
    if [ ${exit_code} -eq 1 ]; then
        display_error_summary
    fi

    rm -f "$ERROR_LOG_FILE"
    
    exit ${exit_code}
}

trap cleanup_monitor EXIT

# Example usage:
# echo "The metadata.json file contains invalid JSON syntax." >&2
# echo "Failed to connect to database." >&2
# exit 1  # This will trigger the error summary display