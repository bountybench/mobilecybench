#!/bin/bash
set -e

echo "=== MobileCybench Orchestrator Container Starting ==="

# Function to check if emulator is needed
check_emulator_needed() {
    if [ "${SKIP_EMULATOR}" = "true" ]; then
        echo "Skipping emulator (SKIP_EMULATOR=true)"
        return 1
    fi
    return 0
}

# Function to start Xvfb for headless display
start_xvfb() {
    echo "Starting Xvfb for headless display..."
    Xvfb :99 -screen 0 1920x1080x24 &
    export DISPLAY=:99
    sleep 2
}

# Function to check KVM availability
check_kvm() {
    echo "Checking KVM availability..."
    if [ -e /dev/kvm ]; then
        echo "KVM is available - hardware acceleration enabled"
        export ANDROID_EMULATOR_USE_SYSTEM_LIBS=1
        return 0
    else
        echo "WARNING: KVM is not available - emulator will run without hardware acceleration"
        echo "To enable KVM, run Docker with: --device /dev/kvm"
        return 1
    fi
}

# Function to start Android emulator
start_emulator() {
    echo "Starting Android emulator..."

    # Check for existing emulator process
    if pgrep -x "emulator" > /dev/null; then
        echo "Emulator is already running"
        return 0
    fi

    # Start emulator with appropriate settings
    local EMU_ARGS="-avd MobileCybenchEmu -no-snapshot-save -wipe-data -memory 2048"

    # Add GPU settings based on environment
    if check_kvm; then
        EMU_ARGS="$EMU_ARGS -gpu host"
    else
        EMU_ARGS="$EMU_ARGS -gpu swiftshader_indirect -no-accel"
    fi

    # Add headless mode settings
    if [ "${HEADLESS_MODE}" = "true" ] || [ -z "${DISPLAY}" ]; then
        EMU_ARGS="$EMU_ARGS -no-window -no-audio -no-boot-anim"
    fi

    echo "Emulator arguments: $EMU_ARGS"

    # Start emulator in background
    emulator $EMU_ARGS > /var/log/emulator.log 2>&1 &

    echo "Waiting for emulator to boot..."

    # Wait for device to be ready (timeout after 5 minutes)
    local timeout=300
    local elapsed=0
    while [ $elapsed -lt $timeout ]; do
        if adb devices | grep -q "emulator.*device"; then
            echo "Emulator detected, waiting for boot completion..."

            # Wait for boot to complete
            while [ "$(adb shell getprop sys.boot_completed 2>/dev/null)" != "1" ]; do
                sleep 5
                elapsed=$((elapsed + 5))
                if [ $elapsed -ge $timeout ]; then
                    echo "ERROR: Emulator boot timeout"
                    return 1
                fi
            done

            echo "Emulator booted successfully!"

            # Display device info
            echo "Android version: $(adb shell getprop ro.build.version.release)"
            echo "SDK version: $(adb shell getprop ro.build.version.sdk)"
            echo "Device: $(adb shell getprop ro.product.model)"

            return 0
        fi
        sleep 5
        elapsed=$((elapsed + 5))
    done

    echo "ERROR: Emulator failed to start within timeout"
    return 1
}

# Function to install Python requirements if mounted
install_requirements() {
    if [ -f "/mobilecybench/requirements.txt" ]; then
        echo "Installing Python requirements..."
        pip install -r /mobilecybench/requirements.txt
    else
        echo "No requirements.txt found, skipping Python package installation"
    fi
}

# Function to setup the environment
setup_environment() {
    echo "Setting up environment..."

    # Set up Android SDK paths
    export PATH="${ANDROID_SDK_ROOT}/cmdline-tools/latest/bin:${ANDROID_SDK_ROOT}/platform-tools:${ANDROID_SDK_ROOT}/emulator:${PATH}"

    # Set up Python path if mobilecybench is mounted
    if [ -d "/mobilecybench" ]; then
        export PYTHONPATH="/mobilecybench:${PYTHONPATH}"
    fi

    # Create necessary directories
    mkdir -p /var/log /var/run/emulator

    echo "Environment setup complete"
}

# Main execution
main() {
    # Setup environment
    setup_environment

    # Install Python requirements if available
    install_requirements

    # Start Xvfb if in headless mode
    if [ "${HEADLESS_MODE}" = "true" ] || [ -z "${DISPLAY}" ]; then
        start_xvfb
    fi

    # Check KVM availability
    check_kvm || true

    # Start emulator if needed
    if check_emulator_needed; then
        if ! start_emulator; then
            echo "WARNING: Emulator failed to start, but continuing..."
        fi
    fi

    # If a command was passed, execute it
    if [ $# -gt 0 ]; then
        echo "Executing command: $@"
        exec "$@"
    else
        echo "Container ready. Waiting for commands..."
        # Keep container running
        tail -f /dev/null
    fi
}

# Handle signals gracefully
trap 'echo "Received signal, shutting down..."; adb emu kill 2>/dev/null || true; exit 0' SIGTERM SIGINT

# Run main function with all arguments
main "$@"