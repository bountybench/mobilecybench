#!/bin/bash
# Emulator recovery script
# Attempts to recover or restart the emulator when it's in a bad state

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

LOG_PREFIX="[recovery]"
info() { echo "$LOG_PREFIX $*" >&2; }
warn() { echo "$LOG_PREFIX[WARN] $*" >&2; }
error() { echo "$LOG_PREFIX[ERROR] $*" >&2; }

# Attempt lightweight recovery first (restart services)
try_lightweight_recovery() {
    info "Attempting lightweight recovery (restart ADB)..."

    # Kill and restart ADB server
    adb kill-server 2>/dev/null || true
    sleep 2
    adb start-server

    # Wait for device
    if adb wait-for-device shell echo "test" >/dev/null 2>&1; then
        info "✓ ADB reconnected"

        # Check if PM is now responsive
        if timeout 10 adb shell pm path android >/dev/null 2>&1; then
            info "✓ Lightweight recovery succeeded"
            return 0
        fi
    fi

    warn "Lightweight recovery failed"
    return 1
}

# Full emulator restart with clean state
do_full_restart() {
    info "Performing full emulator restart with clean state..."

    # Stop emulator
    info "Stopping emulator..."
    if [ -f "$ROOT_DIR/stop_emulator.sh" ]; then
        bash "$ROOT_DIR/stop_emulator.sh" || true
    else
        adb emu kill 2>/dev/null || true
    fi

    # Force kill any remaining emulator processes
    pkill -9 -f qemu-system 2>/dev/null || true
    sleep 3

    # Kill ADB server to ensure clean state
    adb kill-server 2>/dev/null || true
    sleep 2

    # Start fresh emulator with wiped data
    info "Starting fresh emulator (this may take a few minutes)..."
    if [ -f "$ROOT_DIR/start_emulator.sh" ]; then
        WIPE_DATA=true bash "$ROOT_DIR/start_emulator.sh"
    else
        error "start_emulator.sh not found at $ROOT_DIR/start_emulator.sh"
        return 1
    fi

    # Wait for boot
    info "Waiting for emulator to boot..."
    adb wait-for-device
    sleep 5

    # Wait for boot_completed
    local max_wait=300
    local elapsed=0
    while [ $elapsed -lt $max_wait ]; do
        local boot_complete
        boot_complete=$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')
        if [ "$boot_complete" = "1" ]; then
            info "✓ Emulator booted successfully"
            break
        fi
        sleep 2
        elapsed=$((elapsed + 2))
    done

    if [ $elapsed -ge $max_wait ]; then
        error "Emulator did not boot within ${max_wait}s"
        return 1
    fi

    # Wait for PM to be ready
    info "Waiting for PackageManager to be ready..."
    local pm_wait=0
    while [ $pm_wait -lt 60 ]; do
        if timeout 10 adb shell pm path android >/dev/null 2>&1; then
            info "✓ PackageManager is ready"
            break
        fi
        sleep 2
        pm_wait=$((pm_wait + 2))
    done

    # Extra stabilization time
    info "Allowing System UI to stabilize..."
    sleep 15

    info "✓ Full restart complete"
    return 0
}

# Main recovery logic
main() {
    info "========== Starting Emulator Recovery =========="

    # Try lightweight recovery first
    if try_lightweight_recovery; then
        info "========== Recovery Successful (Lightweight) =========="
        return 0
    fi

    # If lightweight fails, do full restart
    if do_full_restart; then
        info "========== Recovery Successful (Full Restart) =========="
        return 0
    fi

    error "========== Recovery Failed =========="
    return 1
}

main "$@"
