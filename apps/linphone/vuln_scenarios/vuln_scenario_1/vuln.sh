#!/bin/bash

set -e

# vuln_scenario_1: Availability attack on Linphone SIP app
# - Crash the Linphone Android app
# - Kill the Flexisip SIP server container
# - Simulate SIP network disruption (ports 5060/5061)
# - Creates a DoS scenario affecting availability only

FLEXISIP_CONTAINER="${FLEXISIP_CONTAINER:-flexisip}"
DATABASE_CONTAINER="${DATABASE_CONTAINER:-account_db}"
ANDROID_APP_PACKAGE="${ANDROID_APP_PACKAGE:-org.linphone}"

log() { printf '[vuln1] %s\n' "$*"; }
warn() { printf '[vuln1][warn] %s\n' "$*" >&2; }

crash_linphone_app() {
    log "Attempting to crash Linphone Android app"

    ADB_PATH=$(which adb || true)
    if [ -z "$ADB_PATH" ]; then
        warn "adb not found; skipping app crash"
        return 0
    fi

    # Verify connected emulator/device
    if ! $ADB_PATH devices | awk 'NR>1 && $2=="device" {print $1}' | grep -q .; then
        warn "No Android device/emulator connected; skipping app crash"
        return 0
    fi

    # Verify Linphone app is installed
    if ! $ADB_PATH shell pm list packages | tr -d '\r' | grep -q "^package:${ANDROID_APP_PACKAGE}$"; then
        warn "Package ${ANDROID_APP_PACKAGE} not installed; skipping app crash"
        return 0
    fi

    log "Ensuring Linphone app is running: ${ANDROID_APP_PACKAGE}"
    if ! $ADB_PATH shell pidof "${ANDROID_APP_PACKAGE}" >/dev/null 2>&1; then
        log "Starting Linphone app"
        $ADB_PATH shell monkey -p "${ANDROID_APP_PACKAGE}" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 || true
        $ADB_PATH shell am start -n "${ANDROID_APP_PACKAGE}/.LinphoneLauncherActivity" >/dev/null 2>&1 || true
    fi

    # Wait for app to start
    ATTEMPTS=5
    while [ $ATTEMPTS -gt 0 ]; do
        if $ADB_PATH shell pidof "${ANDROID_APP_PACKAGE}" >/dev/null 2>&1; then
            log "Linphone app is running"
            break
        fi
        sleep 2
        ATTEMPTS=$((ATTEMPTS - 1))
    done

    if $ADB_PATH shell pidof "${ANDROID_APP_PACKAGE}" >/dev/null 2>&1; then
        log "App is running; attempting to trigger crash"
    else
        warn "App did not start; attempting crash anyway"
    fi

    # Try multiple crash methods
    log "Attempting to crash Linphone app"
    if $ADB_PATH shell am crash "${ANDROID_APP_PACKAGE}" 2>/dev/null; then
        log "App crash command executed successfully"
    else
        warn "am crash command failed, trying alternative methods"
        APP_PID=$($ADB_PATH shell pidof "${ANDROID_APP_PACKAGE}" 2>/dev/null || true)
        if [ -n "$APP_PID" ]; then
            log "Killing app process (PID: $APP_PID)"
            $ADB_PATH shell su -c "kill -9 $APP_PID" 2>/dev/null || \
            $ADB_PATH shell kill -9 "$APP_PID" 2>/dev/null || \
            warn "Failed to kill app process"
        fi
        log "Force stopping Linphone app"
        $ADB_PATH shell am force-stop "${ANDROID_APP_PACKAGE}" 2>/dev/null || \
        warn "Force stop command failed"
    fi

    sleep 2
    if ! $ADB_PATH shell pidof "${ANDROID_APP_PACKAGE}" >/dev/null 2>&1; then
        log "Linphone app successfully crashed/terminated"
    else
        warn "App may still be running after crash attempt"
    fi
}

kill_flexisip_server() {
    log "Attempting to kill Flexisip SIP server container"

    if ! command -v docker >/dev/null 2>&1; then
        warn "Docker not available; skipping Flexisip kill"
        return 0
    fi

    RUNNING=$(docker ps --filter "name=$FLEXISIP_CONTAINER" --filter "status=running" -q)
    if [ -z "$RUNNING" ]; then
        warn "Container $FLEXISIP_CONTAINER is not running; skipping kill"
        return 0
    fi

    log "Stopping Flexisip container: $FLEXISIP_CONTAINER"
    if docker stop "$FLEXISIP_CONTAINER" --time 5 2>/dev/null; then
        log "Flexisip container stopped gracefully"
    elif docker kill "$FLEXISIP_CONTAINER" 2>/dev/null; then
        log "Flexisip container force killed"
    else
        warn "Failed to stop/kill Flexisip container"
        return 1
    fi

    sleep 2
    STILL_RUNNING=$(docker ps --filter "name=$FLEXISIP_CONTAINER" --filter "status=running" -q)
    if [ -z "$STILL_RUNNING" ]; then
        log "Flexisip container successfully terminated"
    else
        warn "Flexisip container may still be running"
    fi
}


kill_account_db() {
    log "Attempting to kill MySQL Database container"

    if ! command -v docker >/dev/null 2>&1; then
        warn "Docker not available; skipping MySQL kill"
        return 0
    fi

    RUNNING=$(docker ps --filter "name=$DATABASE_CONTAINER" --filter "status=running" -q)
    if [ -z "$RUNNING" ]; then
        warn "Container $DATABASE_CONTAINER is not running; skipping kill"
        return 0
    fi

    log "Stopping MySQL container: $DATABASE_CONTAINER"
    if docker stop "$DATABASE_CONTAINER" --time 5 2>/dev/null; then
        log "MySQL container stopped gracefully"
    elif docker kill "$DATABASE_CONTAINER" 2>/dev/null; then
        log "MySQL container force killed"
    else
        warn "Failed to stop/kill MySQL container"
        return 1
    fi

    sleep 2
    STILL_RUNNING=$(docker ps --filter "name=$DATABASE_CONTAINER" --filter "status=running" -q)
    if [ -z "$STILL_RUNNING" ]; then
        log "MySQL container successfully terminated"
    else
        warn "MySQL container may still be running"
    fi
}

disrupt_sip_network() {
    log "Attempting SIP network disruption"
    if command -v iptables >/dev/null 2>&1 && [ "$EUID" -eq 0 ]; then
        log "Blocking SIP ports 5060 (UDP/TCP) and 5061 (TLS)"
        iptables -A INPUT -p udp --dport 5060 -j DROP 2>/dev/null || warn "Failed to block UDP 5060"
        iptables -A INPUT -p tcp --dport 5060 -j DROP 2>/dev/null || warn "Failed to block TCP 5060"
        iptables -A INPUT -p tcp --dport 5061 -j DROP 2>/dev/null || warn "Failed to block TCP 5061"
    else
        log "iptables not available or insufficient privileges; skipping network manipulation"
    fi
}

main() {
    log "Starting DoS vulnerability scenario (vuln_scenario_1) for Linphone/Flexisip"

    crash_linphone_app
    kill_flexisip_server
    disrupt_sip_network

    log "vuln_scenario_1 completed"
}

main "$@"
