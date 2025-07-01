#!/bin/bash
# Check if Android device is ready

ANDROID_HOME="${HOME}/.android-sdk"

echo "Checking Android device status..."

# Check if ADB is available
if ! command -v adb >/dev/null 2>&1; then
    if [[ -f "$ANDROID_HOME/platform-tools/adb" ]]; then
        export PATH="$ANDROID_HOME/platform-tools:$PATH"
    else
        echo "ERROR: ADB not found. Please run setup.sh first."
        exit 1
    fi
fi

# Check for connected devices
devices=$(adb devices | grep -v "List of devices" | grep -E "device$|emulator")

if [[ -z "$devices" ]]; then
    echo "No Android devices found."
    echo "Run ./start_emulator.sh to start the emulator."
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
    
    # Check architecture
    arch=$(adb -s "$device_id" shell getprop ro.product.cpu.abi)
    echo "Architecture: $arch"
    
    exit 0
else
    echo "Device connectivity test failed."
    exit 1
fi
