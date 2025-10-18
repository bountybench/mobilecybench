#!/bin/bash
# Start Android emulator based on SDK version
# Usage: ./start_emulator.sh <sdk_version>

set -e

# Check if SDK version argument is provided
if [ -z "$1" ]; then
    echo "Error: SDK version is required"
    echo "Usage: $0 <sdk_version>"
    exit 1
fi

SDK_VERSION="$1"
ANDROID_HOME="${HOME}/.android-sdk"

# Construct emulator name based on SDK version
EMULATOR_NAME="MobileCybenchEmulatorAPI${SDK_VERSION}"

echo "SDK Version: $SDK_VERSION"
echo "Emulator: $EMULATOR_NAME"

# Check if emulator is already running
check_running_emulator() {
    local running_emulators
    if command -v adb >/dev/null 2>&1; then
        running_emulators=$(adb devices | grep -E "emulator-[0-9]+.*device$" | wc -l)
    elif [[ -f "$ANDROID_HOME/platform-tools/adb" ]]; then
        running_emulators=$("$ANDROID_HOME/platform-tools/adb" devices | grep -E "emulator-[0-9]+.*device$" | wc -l)
    else
        echo "Warning: ADB not found, cannot check for running emulators"
        return 0
    fi

    if [[ $running_emulators -gt 0 ]]; then
        echo "Warning: There are $running_emulators Android emulator(s) already running."
        echo "Continuing in Docker mode (no user prompt)..."
    fi
}

# Check for running emulators before starting
check_running_emulator

echo "Starting Android emulator: $EMULATOR_NAME (headless mode)"
echo "This may take a few minutes on first boot..."

"$ANDROID_HOME/emulator/emulator" \
    -avd "$EMULATOR_NAME" \
    -no-snapshot-save \
    -wipe-data \
    -no-window \
    -gpu off \
    -memory 2048 \
    -no-audio \
    -read-only \
    &

echo "Emulator started in background (headless)"
echo "Waiting for device to be ready..."

# Wait for device
"$ANDROID_HOME/platform-tools/adb" wait-for-device

echo "Device ready!"
echo "To check device status: adb devices"
