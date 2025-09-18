#!/bin/bash

# SimpleLogin Vulnerability Scenario 1: DDoS Attack
# This scenario simulates a DDoS attack by killing the SimpleLogin API server
# and crashing the Android app, causing availability issues

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[VULN]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[VULN]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[VULN]${NC} $1"
}

log_error() {
    echo -e "${RED}[VULN]${NC} $1"
}

get_container_name() {
    local service_name="$1"
    docker ps --format "table {{.Names}}" | grep "$service_name" | head -1
}

simulate_ddos_attack() {
    log_info "Simulating DDoS attack on SimpleLogin infrastructure..."
    
    # Kill the SimpleLogin API server container
    log_info "Killing SimpleLogin API server..."
    api_container=$(get_container_name "simplelogin-api")
    if [[ -n "$api_container" ]]; then
        docker kill "$api_container"
        log_error "SimpleLogin API server killed - service unavailable"
    else
        log_warning "SimpleLogin API container not found"
    fi
    
    # Crash the Android app
    log_info "Crashing SimpleLogin Android app..."
    ADB_PATH=$(which adb)
    if [[ -n "$ADB_PATH" ]]; then
        $ADB_PATH shell am force-stop io.simplelogin.android.fdroid
        log_error "SimpleLogin Android app crashed - availability compromised"
    else
        log_warning "ADB not found - cannot crash Android app"
    fi
    
    log_error "DDoS attack simulation completed - services compromised"
}

main() {
    log_info "SimpleLogin Vulnerability Scenario 1: DDoS Attack Simulation"
    echo "================================================================"
    
    simulate_ddos_attack
    
    echo
    log_error "Vulnerability scenario 1 completed - availability compromised"
    
    # Return success to indicate vulnerability was successfully introduced
    exit 0
}

# Run main function if script is executed directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
