#!/bin/bash

# ANSI color codes
RED="\033[91m"
RESET="\033[0m"
ERROR="${RED}[ERROR]${RESET}"

# Error buffer configuration
ERROR_LOG=()
ERROR_COUNT=0

log_error() {
    local message="$1"
    local formatted_error="${ERROR} ${message}"

    ERROR_LOG+=("${formatted_error}")
    
    ((ERROR_COUNT++))

    echo -e "${formatted_error}" >&2
}

# Function to display all buffered errors
display_error_summary() {
    if [ ${ERROR_COUNT} -gt 0 ]; then
        echo -e "\n${RED}=== Error Summary ===${RESET}" >&2
        echo -e "${RED}Total errors encountered: ${ERROR_COUNT}${RESET}" >&2
        
        if [ ${ERROR_COUNT} -gt ${MAX_ERRORS} ]; then
            echo -e "${RED}(Showing first ${MAX_ERRORS} errors)${RESET}" >&2
        fi
        
        echo "" >&2
        for error in "${ERROR_LOG[@]}"; do
            echo -e "${error}" >&2
        done
        echo -e "${RED}=====================${RESET}\n" >&2
    fi
}

# Trap EXIT signal to display error summary when script exits with code 1
cleanup_and_exit() {
    local exit_code=$?
    if [ ${exit_code} -eq 1 ]; then
        display_error_summary
    fi
    exit ${exit_code}
}

trap cleanup_and_exit EXIT

# Example usage:
# log_error "The metadata.json file contains invalid JSON syntax."
# log_error "Failed to connect to database."
# exit 1  # This will trigger the error summary display