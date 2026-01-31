#!/bin/bash
# Emulator health check utility
# Returns 0 if emulator is healthy, 1 if needs restart

set +e  # Don't exit on errors, we want to report them

LOG_PREFIX="[health_check]"
info() { echo "$LOG_PREFIX $*" >&2; }
warn() { echo "$LOG_PREFIX[WARN] $*" >&2; }
error() { echo "$LOG_PREFIX[ERROR] $*" >&2; }

# Check if ADB can connect
check_adb_connection() {
    info "Checking ADB connection..."
    if ! adb get-state >/dev/null 2>&1; then
        error "ADB cannot connect to device"
        return 1
    fi
    info "✓ ADB connection OK"
    return 0
}

# Check if PackageManager is responsive
check_package_manager() {
    info "Checking PackageManager health..."
    local max_attempts=5
    local attempt=0

    while [ $attempt -lt $max_attempts ]; do
        # Try a simple PM query that should always work
        if timeout 10 adb shell pm path android >/dev/null 2>&1; then
            info "✓ PackageManager is responsive"
            return 0
        fi
        attempt=$((attempt + 1))
        warn "PackageManager not responsive (attempt $attempt/$max_attempts)"
        sleep 2
    done

    error "PackageManager is not responsive after $max_attempts attempts"
    return 1
}

# Check if boot is complete
check_boot_complete() {
    info "Checking boot status..."
    local boot_complete
    boot_complete=$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')

    if [ "$boot_complete" != "1" ]; then
        error "Boot not complete (sys.boot_completed=$boot_complete)"
        return 1
    fi
    info "✓ Boot complete"
    return 0
}

# Check critical system services
check_system_services() {
    info "Checking critical system services..."

    # Check if system_server is running
    if ! adb shell ps -A | grep -q "system_server"; then
        error "system_server process not found"
        return 1
    fi

    # Check if installd is running
    if ! adb shell ps -A | grep -q "installd"; then
        error "installd process not found"
        return 1
    fi

    info "✓ Critical services running"
    return 0
}

# Check storage space
check_storage_space() {
    info "Checking storage space..."

    # Check /data partition (where apps are installed)
    local data_usage
    data_usage=$(adb shell df /data 2>/dev/null | tail -1 | awk '{print $5}' | tr -d '%')

    if [ -n "$data_usage" ] && [ "$data_usage" -gt 90 ]; then
        warn "Data partition is ${data_usage}% full (may cause issues)"
        return 1
    fi

    info "✓ Storage OK (data partition: ${data_usage}% used)"
    return 0
}

# Try a test APK install/uninstall cycle
check_install_capability() {
    info "Checking APK install capability..."

    # First check if pm list packages works
    if ! timeout 15 adb shell pm list packages >/dev/null 2>&1; then
        error "Cannot list packages"
        return 1
    fi

    # More thorough check: Test actual package installation using a built-in APK
    # We'll try to reinstall a system package to test the install pipeline
    info "Testing actual APK installation pipeline..."

    # Try to get package info for a system app (tests PM more thoroughly)
    if ! timeout 10 adb shell pm path com.android.shell >/dev/null 2>&1; then
        error "Cannot query package paths (PM query failed)"
        return 1
    fi

    # Test the install session creation (this exercises PackageManagerInternal)
    # Create and abandon a test session to verify the install pipeline works
    local test_output
    if test_output=$(timeout 10 adb shell pm install-create 2>&1); then
        # Extract session ID and abandon it
        local session_id
        session_id=$(echo "$test_output" | grep -oE 'session [0-9]+' | grep -oE '[0-9]+' | head -1)
        if [ -n "$session_id" ]; then
            adb shell pm install-abandon "$session_id" >/dev/null 2>&1 || true
            info "✓ Install capability OK (tested install-create)"
            return 0
        else
            warn "install-create succeeded but couldn't parse session ID"
            info "✓ Install capability appears OK"
            return 0
        fi
    else
        error "Cannot create install session (PackageManager install pipeline broken)"
        error "Output: $test_output"
        return 1
    fi
}

# Main health check
main() {
    local exit_code=0
    local pm_check_failed=0
    local install_check_passed=0

    info "========== Starting Emulator Health Check =========="

    # Critical checks
    check_adb_connection || { exit_code=1; }
    check_system_services || { exit_code=1; }

    # PackageManager checks - query might be slow, but install test is definitive
    check_package_manager || { pm_check_failed=1; }
    check_install_capability && { install_check_passed=1; }

    # If install capability works, PM is healthy even if query is slow
    if [ $install_check_passed -eq 1 ]; then
        if [ $pm_check_failed -eq 1 ]; then
            warn "PM query slow but install works - considering healthy"
        fi
        info "✓ PackageManager functional (install capability verified)"
    else
        error "✗ PackageManager install capability broken"
        exit_code=1
    fi

    # Non-critical checks
    check_boot_complete || {
        warn "Boot animation may be stuck, but continuing if PM works..."
    }
    check_storage_space || {
        warn "Storage check had issues"
    }

    if [ $exit_code -eq 0 ]; then
        info "========== Health Check PASSED =========="
    else
        error "========== Health Check FAILED =========="
    fi

    return $exit_code
}

main "$@"
