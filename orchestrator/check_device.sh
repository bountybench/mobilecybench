#!/bin/bash
# Check if Android device is ready (Docker mode)

set -e

echo "Checking Android device status..."

# Check if ADB is available
if ! command -v adb >/dev/null 2>&1; then
    echo "ERROR: ADB not found in PATH."
    exit 1
fi

# Check for connected devices
devices=$(adb devices | grep -v "List of devices" | grep -E "device$|emulator")

if [[ -z "$devices" ]]; then
    echo "No Android devices found."
    echo "Please ensure the emulator is running."
    exit 1
fi

echo "Connected devices:"
echo "$devices"

# Test device connectivity
device_id=$(echo "$devices" | head -n1 | awk '{print $1}')
echo "Testing device connectivity..."

if adb -s "$device_id" shell echo "test" >/dev/null 2>&1; then
    echo "Device is ready!"

    # Check Android version
    android_version=$(adb -s "$device_id" shell getprop ro.build.version.release)
    echo "Android version: $android_version"

    # Check SDK version (API level)
    sdk_version=$(adb -s "$device_id" shell getprop ro.build.version.sdk)
    echo "SDK version (API level): $sdk_version"

    # Check architecture
    arch=$(adb -s "$device_id" shell getprop ro.product.cpu.abi)
    echo "Architecture: $arch"

    # Check if device is fully booted
    boot_completed=$(adb -s "$device_id" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')
    if [[ "$boot_completed" == "1" ]]; then
        echo "Boot status: Completed"
    else
        echo "Boot status: Still booting..."
        exit 1
    fi

    exit 0
else
    echo "Device connectivity test failed."
    exit 1
fi
