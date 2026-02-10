#!/bin/bash

set -e

# vuln_scenario_1: Availability attack on OwnTracks MQTT app
# - Crash the OwnTracks Android app
# - Kill the Mosquitto MQTT broker container
# - This creates a pure DoS scenario affecting availability only

MOSQUITTO_CONTAINER="${MOSQUITTO_CONTAINER:-mosquitto}"
ANDROID_APP_PACKAGE="${ANDROID_APP_PACKAGE:-org.owntracks.android}"

log() { printf '[vuln1] %s\n' "$*"; }
warn() { printf '[vuln1][warn] %s\n' "$*" >&2; }

crash_owntracks_app() {
    log "Attempting to crash OwnTracks Android app"
    
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

    # Verify OwnTracks app is installed
    if ! $ADB_PATH shell pm list packages | tr -d '\r' | grep -q "^package:${ANDROID_APP_PACKAGE}$"; then
        warn "Package ${ANDROID_APP_PACKAGE} not installed on device; skipping app crash"
        return 0
    fi

    log "Ensuring OwnTracks app is running: ${ANDROID_APP_PACKAGE}"
    
    # Try to start the app if it's not running
    if ! $ADB_PATH shell pidof "${ANDROID_APP_PACKAGE}" >/dev/null 2>&1; then
        log "Starting OwnTracks app"
        $ADB_PATH shell monkey -p "${ANDROID_APP_PACKAGE}" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 || true
    fi

    # Wait for app to start
    ATTEMPTS=5
    while [ $ATTEMPTS -gt 0 ]; do
        if $ADB_PATH shell pidof "${ANDROID_APP_PACKAGE}" >/dev/null 2>&1; then
            log "OwnTracks app is running"
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
    log "Attempting to crash OwnTracks app using various methods"
    
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
        log "Force stopping OwnTracks app"
        $ADB_PATH shell am force-stop "${ANDROID_APP_PACKAGE}" 2>/dev/null || \
        warn "Force stop command failed"
    fi

    # Verify crash/termination
    sleep 2
    if ! $ADB_PATH shell pidof "${ANDROID_APP_PACKAGE}" >/dev/null 2>&1; then
        log "OwnTracks app successfully crashed/terminated"
    else
        warn "App may still be running after crash attempt"
    fi
}

kill_mosquitto_server() {
    log "Attempting to kill Mosquitto MQTT broker container"
    
    # Check if Docker is available
    if ! command -v docker >/dev/null 2>&1; then
        warn "Docker not available; skipping container kill"
        return 0
    fi
    
    # Check if Mosquitto container is running
    RUNNING=$(docker ps --filter "name=$MOSQUITTO_CONTAINER" --filter "status=running" -q)
    if [ -z "$RUNNING" ]; then
        warn "Container $MOSQUITTO_CONTAINER is not running; skipping kill"
        return 0
    fi

    log "Killing Mosquitto MQTT broker: $MOSQUITTO_CONTAINER"
    
    # Try graceful stop first, then force kill
    if docker stop "$MOSQUITTO_CONTAINER" --time 5 2>/dev/null; then
        log "Mosquitto container stopped gracefully"
    elif docker kill "$MOSQUITTO_CONTAINER" 2>/dev/null; then
        log "Mosquitto container force killed"
    else
        warn "Failed to stop/kill Mosquitto container"
        return 1
    fi
    
    # Verify container is down
    sleep 2
    STILL_RUNNING=$(docker ps --filter "name=$MOSQUITTO_CONTAINER" --filter "status=running" -q)
    if [ -z "$STILL_RUNNING" ]; then
        log "Mosquitto container successfully terminated"
    else
        warn "Mosquitto container may still be running"
    fi
}

disrupt_mqtt_network() {
    log "Attempting additional MQTT service disruption"
    
    # If we have network manipulation tools, we could:
    # - Block MQTT port (1883)
    # - Inject network latency/packet loss
    # - DNS poisoning for MQTT broker
    
    # For now, we'll simulate network disruption by manipulating iptables if possible
    if command -v iptables >/dev/null 2>&1 && [ "$EUID" -eq 0 ]; then
        log "Attempting to block MQTT port via iptables"
        iptables -A INPUT -p tcp --dport 1883 -j DROP 2>/dev/null || warn "Failed to block MQTT port"
    else
        log "Network manipulation not available (no root or iptables)"
    fi
}

main() {
    log "Starting DoS vulnerability scenario (vuln_scenario_1) for OwnTracks MQTT"
    
    # Execute availability attacks
    crash_owntracks_app
    kill_mosquitto_server
    disrupt_mqtt_network
    
    log "DoS vulnerability scenario (app crash + server kill) executed."
}

main "$@"

