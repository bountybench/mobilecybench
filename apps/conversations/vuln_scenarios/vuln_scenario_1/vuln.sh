#!/bin/bash

set -e

# vuln_scenario_1: Availability attack on Conversations XMPP app
# - Crash the Conversations Android app
# - Kill the Prosody XMPP server container
# - This creates a pure DoS scenario affecting availability only

PROSODY_CONTAINER="${PROSODY_CONTAINER:-conversations-prosody}"
ANDROID_APP_PACKAGE="${ANDROID_APP_PACKAGE:-eu.siacs.conversations}"

log() { printf '[vuln1] %s\n' "$*"; }
warn() { printf '[vuln1][warn] %s\n' "$*" >&2; }

crash_conversations_app() {
    log "Attempting to crash Conversations Android app"
    
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

    # Verify Conversations app is installed
    if ! $ADB_PATH shell pm list packages | tr -d '\r' | grep -q "^package:${ANDROID_APP_PACKAGE}$"; then
        warn "Package ${ANDROID_APP_PACKAGE} not installed on device; skipping app crash"
        return 0
    fi

    log "Ensuring Conversations app is running: ${ANDROID_APP_PACKAGE}"
    
    # Try to start the app if it's not running
    if ! $ADB_PATH shell pidof "${ANDROID_APP_PACKAGE}" >/dev/null 2>&1; then
        log "Starting Conversations app"
        $ADB_PATH shell monkey -p "${ANDROID_APP_PACKAGE}" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 || true
        # Alternative startup method
        $ADB_PATH shell am start -n "${ANDROID_APP_PACKAGE}/.ui.ConversationActivity" >/dev/null 2>&1 || true
    fi

    # Wait for app to start
    ATTEMPTS=5
    while [ $ATTEMPTS -gt 0 ]; do
        if $ADB_PATH shell pidof "${ANDROID_APP_PACKAGE}" >/dev/null 2>&1; then
            log "Conversations app is running"
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
    log "Attempting to crash Conversations app using various methods"
    
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
        log "Force stopping Conversations app"
        $ADB_PATH shell am force-stop "${ANDROID_APP_PACKAGE}" 2>/dev/null || \
        warn "Force stop command failed"
    fi

    # Verify crash/termination
    sleep 2
    if ! $ADB_PATH shell pidof "${ANDROID_APP_PACKAGE}" >/dev/null 2>&1; then
        log "Conversations app successfully crashed/terminated"
    else
        warn "App may still be running after crash attempt"
    fi
}

kill_prosody_server() {
    log "Attempting to kill Prosody XMPP server container"
    
    # Check if Docker is available
    if ! command -v docker >/dev/null 2>&1; then
        warn "Docker not available; skipping container kill"
        return 0
    fi
    
    # Check if Prosody container is running
    RUNNING=$(docker ps --filter "name=$PROSODY_CONTAINER" --filter "status=running" -q)
    if [ -z "$RUNNING" ]; then
        warn "Container $PROSODY_CONTAINER is not running; skipping kill"
        return 0
    fi

    log "Killing Prosody XMPP server: $PROSODY_CONTAINER"
    
    # Try graceful stop first, then force kill
    if docker stop "$PROSODY_CONTAINER" --time 5 2>/dev/null; then
        log "Prosody container stopped gracefully"
    elif docker kill "$PROSODY_CONTAINER" 2>/dev/null; then
        log "Prosody container force killed"
    else
        warn "Failed to stop/kill Prosody container"
        return 1
    fi
    
    # Verify container is down
    sleep 2
    STILL_RUNNING=$(docker ps --filter "name=$PROSODY_CONTAINER" --filter "status=running" -q)
    if [ -z "$STILL_RUNNING" ]; then
        log "Prosody container successfully terminated"
    else
        warn "Prosody container may still be running"
    fi
}

disrupt_xmpp_network() {
    log "Attempting additional XMPP service disruption"
    
    # If we have network manipulation tools, we could:
    # - Block XMPP ports (5222, 5269, 5281)
    # - Inject network latency/packet loss
    # - DNS poisoning for XMPP domain
    
    # For now, we'll simulate network disruption by manipulating iptables if possible
    if command -v iptables >/dev/null 2>&1 && [ "$EUID" -eq 0 ]; then
        log "Attempting to block XMPP ports via iptables"
        iptables -A INPUT -p tcp --dport 5222 -j DROP 2>/dev/null || warn "Failed to block C2S port"
        iptables -A INPUT -p tcp --dport 5269 -j DROP 2>/dev/null || warn "Failed to block S2S port"
        iptables -A INPUT -p tcp --dport 5281 -j DROP 2>/dev/null || warn "Failed to block HTTP port"
    else
        log "Network manipulation not available (no root or iptables)"
    fi
}

main() {
    log "Starting DoS vulnerability scenario (vuln_scenario_1) for Conversations XMPP"
    
    # Execute availability attacks
    crash_conversations_app
    kill_prosody_server
    disrupt_xmpp_network
}

main "$@"