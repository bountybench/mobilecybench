#!/bin/bash
# Start Android emulator

ANDROID_HOME="${HOME}/.android-sdk"
EMULATOR_NAME="MobileCybenchEmu"

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
        echo "Starting another emulator may cause performance issues or conflicts."
        echo ""
        echo "Current running emulators:"
        if command -v adb >/dev/null 2>&1; then
            adb devices | grep -E "emulator-[0-9]+.*device$"
        else
            "$ANDROID_HOME/platform-tools/adb" devices | grep -E "emulator-[0-9]+.*device$"
        fi
        echo ""
        read -p "Do you want to proceed anyway? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "Emulator start cancelled."
            echo "To stop the currently running emulators, you can use: ./stop_emulator.sh"
            exit 0
        fi
    fi
}

# Check for running emulators before starting
check_running_emulator

echo "Starting Android emulator: $EMULATOR_NAME"
echo "This may take a few minutes on first boot..."

"$ANDROID_HOME/emulator/emulator" \
    -avd "$EMULATOR_NAME" \
    -no-snapshot-save \
    -wipe-data \
    -no-window \
    -gpu off \
    -skin 1080x1920 \
    -memory 2048 \
    &

echo "Emulator started in background"
echo "Waiting for device to be ready..."

# Wait for device
"$ANDROID_HOME/platform-tools/adb" wait-for-device

echo "Device ready!"
echo "To check device status: adb devices"
