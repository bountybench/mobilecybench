#!/bin/bash

# Utility functions for container management
# This script should be sourced by other scripts, not executed directly

# Function to get container name by service
get_container_name_by_service() {
    local service_name="$1"
    local container_id
    local container_name
    
    # Try to get container ID using docker compose ps
    container_id=$(docker ps --filter "name=$service_name" --format "{{.ID}}" 2>/dev/null)
    
    if [ -n "$container_id" ]; then
        # Get the container name from the ID
        container_name=$(docker inspect --format='{{.Name}}' "$container_id" 2>/dev/null | sed 's|^/||')
        if [ -n "$container_name" ]; then
            echo "[INFO] Found container '$container_name' for service '$service_name'" >&2
            echo "$container_name"
            return 0
        fi
    fi
    
    echo "[INFO] Could not find container for service '$service_name', using service name as fallback" >&2
    echo "$service_name"
    return 1
}

# Function to check if this script is being sourced
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "This script is meant to be sourced, not executed directly." >&2
    echo "Usage: source utils.sh" >&2
    exit 1
fi
