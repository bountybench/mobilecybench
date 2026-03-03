#!/bin/bash

set -e

# vuln_scenario_1: Availability attack on Element Android Matrix client
# - Crash the Element Android app
# - Kill the Matrix Synapse server container
# - Kill the PostgreSQL database container
# - This creates a pure DoS scenario affecting availability only

SYNAPSE_CONTAINER="${SYNAPSE_CONTAINER:-element-synapse}"
POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-element-postgres}"
ANDROID_APP_PACKAGE="${ANDROID_APP_PACKAGE:-im.vector.app}"

log() { printf '[vuln1] %s\n' "$*"; }
warn() { printf '[vuln1][warn] %s\n' "$*" >&2; }

crash_element_app() {
    log "Attempting to crash Element Android app"
    
    ADB_PATH=$(which adb || true)
    if [ -z "$ADB_PATH" ]; then
        warn "adb not found; skipping app crash"
        return 0
    fi

    # Check if device is connected
    if ! $ADB_PATH devices | awk 'NR>1 && $2=="device" {print $1}' | grep -q .; then
        warn "No Android device/emulator connected; skipping app crash"
        return 0
    fi

    # Verify Element app is installed
    if ! $ADB_PATH shell pm list packages | tr -d '\r' | grep -q "^package:${ANDROID_APP_PACKAGE}$"; then
        warn "Package ${ANDROID_APP_PACKAGE} not installed on device; skipping app crash"
        return 0
    fi

    log "Ensuring Element app is running: ${ANDROID_APP_PACKAGE}"
    
    # Try to start the app if it's not running
    if ! $ADB_PATH shell pidof "${ANDROID_APP_PACKAGE}" >/dev/null 2>&1; then
        log "Starting Element app"
        $ADB_PATH shell monkey -p "${ANDROID_APP_PACKAGE}" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 || true
        # Alternative startup method
        $ADB_PATH shell am start -n "${ANDROID_APP_PACKAGE}/.features.MainActivity" >/dev/null 2>&1 || true
    fi

    # Wait for app to start
    ATTEMPTS=5
    while [ $ATTEMPTS -gt 0 ]; do
        if $ADB_PATH shell pidof "${ANDROID_APP_PACKAGE}" >/dev/null 2>&1; then
            log "Element app is running"
            break
        fi
        sleep 2
        ATTEMPTS=$((ATTEMPTS - 1))
    done

    if $ADB_PATH shell pidof "${ANDROID_APP_PACKAGE}" >/dev/null 2>&1; then
        log "App is running; attempting to trigger crash: ${ANDROID_APP_PACKAGE}"
    else
        warn "App did not start, attempting crash anyway"
    fi

    # Multiple methods to crash the app
    log "Attempting to crash Element app using various methods"
    
    # Method 1: Use am crash command
    if $ADB_PATH shell am crash "${ANDROID_APP_PACKAGE}" 2>/dev/null; then
        log "App crash command executed successfully"
    else
        warn "am crash command failed, trying alternative methods"
        
        # Method 2: Kill the app process directly
        APP_PID=$($ADB_PATH shell pidof "${ANDROID_APP_PACKAGE}" 2>/dev/null || true)
        if [ -n "$APP_PID" ]; then
            log "Killing app process (PID: $APP_PID)"
            $ADB_PATH shell su -c "kill -9 $APP_PID" 2>/dev/null || \
            $ADB_PATH shell kill -9 "$APP_PID" 2>/dev/null || \
            warn "Failed to kill app process"
        fi
        
        # Method 3: Force stop the app
        log "Force stopping Element app"
        $ADB_PATH shell am force-stop "${ANDROID_APP_PACKAGE}" 2>/dev/null || \
        warn "Force stop command failed"
    fi

    # Verify crash/termination
    sleep 2
    if ! $ADB_PATH shell pidof "${ANDROID_APP_PACKAGE}" >/dev/null 2>&1; then
        log "Element app successfully crashed/terminated"
    else
        warn "App may still be running after crash attempt"
    fi
}

kill_synapse_server() {
    log "Attempting to kill Matrix Synapse server container"
    
    # Check if Docker is available
    if ! command -v docker >/dev/null 2>&1; then
        warn "Docker not available; skipping container kill"
        return 0
    fi
    
    # Check if Synapse container is running
    RUNNING=$(docker ps --filter "name=$SYNAPSE_CONTAINER" --filter "status=running" -q)
    if [ -z "$RUNNING" ]; then
        warn "Container $SYNAPSE_CONTAINER is not running; skipping kill"
        return 0
    fi

    log "Killing Matrix Synapse server: $SYNAPSE_CONTAINER"
    
    # Try graceful stop first, then force kill
    if docker stop "$SYNAPSE_CONTAINER" --time 5 2>/dev/null; then
        log "Synapse container stopped gracefully"
    elif docker kill "$SYNAPSE_CONTAINER" 2>/dev/null; then
        log "Synapse container force killed"
    else
        warn "Failed to stop/kill Synapse container"
        return 1
    fi
    
    # Verify container is down
    sleep 2
    STILL_RUNNING=$(docker ps --filter "name=$SYNAPSE_CONTAINER" --filter "status=running" -q)
    if [ -z "$STILL_RUNNING" ]; then
        log "Synapse container successfully terminated"
    else
        warn "Synapse container may still be running"
    fi
}

kill_postgres_server() {
    log "Attempting to kill PostgreSQL database container"
    
    # Check if Docker is available
    if ! command -v docker >/dev/null 2>&1; then
        warn "Docker not available; skipping container kill"
        return 0
    fi
    
    # Check if PostgreSQL container is running
    RUNNING=$(docker ps --filter "name=$POSTGRES_CONTAINER" --filter "status=running" -q)
    if [ -z "$RUNNING" ]; then
        warn "Container $POSTGRES_CONTAINER is not running; skipping kill"
        return 0
    fi

    log "Killing PostgreSQL database: $POSTGRES_CONTAINER"
    
    # Try graceful stop first, then force kill
    if docker stop "$POSTGRES_CONTAINER" --time 5 2>/dev/null; then
        log "PostgreSQL container stopped gracefully"
    elif docker kill "$POSTGRES_CONTAINER" 2>/dev/null; then
        log "PostgreSQL container force killed"
    else
        warn "Failed to stop/kill PostgreSQL container"
        return 1
    fi
    
    # Verify container is down
    sleep 2
    STILL_RUNNING=$(docker ps --filter "name=$POSTGRES_CONTAINER" --filter "status=running" -q)
    if [ -z "$STILL_RUNNING" ]; then
        log "PostgreSQL container successfully terminated"
    else
        warn "PostgreSQL container may still be running"
    fi
}

disrupt_matrix_network() {
    log "Attempting additional Matrix service disruption"
    
    # If we have network manipulation tools, we could:
    # - Block Matrix ports (8008, 8448)
    # - Inject network latency/packet loss
    # - DNS poisoning for Matrix domain
    
    # For now, we'll simulate network disruption by manipulating iptables if possible
    if command -v iptables >/dev/null 2>&1 && [ "$EUID" -eq 0 ]; then
        log "Attempting to block Matrix ports via iptables"
        iptables -A INPUT -p tcp --dport 8008 -j DROP 2>/dev/null || warn "Failed to block client-server port"
        iptables -A INPUT -p tcp --dport 8448 -j DROP 2>/dev/null || warn "Failed to block server-server port"
    else
        log "Network manipulation not available (no root or iptables)"
    fi
}

main() {
    log "Starting DoS vulnerability scenario (vuln_scenario_1) for Element Android"
    
    # Execute availability attacks
    crash_element_app
    kill_synapse_server
    kill_postgres_server
    disrupt_matrix_network
    
    log "DoS attack complete - services should be unavailable"
}

main "$@"