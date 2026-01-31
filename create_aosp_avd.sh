#!/bin/bash
# Create lightweight AOSP AVD (no Google bloatware)

set -e

ANDROID_HOME="${ANDROID_HOME:-$HOME/.android-sdk}"
SDK_VERSION="${1:-33}"
ARCH="x86_64"

AVDMANAGER="$ANDROID_HOME/cmdline-tools/latest/bin/avdmanager"
SDKMANAGER="$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager"

AVD_NAME="MobileCybenchEmulatorAPI${SDK_VERSION}_aosp"
SYSTEM_IMAGE="system-images;android-${SDK_VERSION};default;${ARCH}"

echo "========================================="
echo "Creating AOSP AVD (No Google Bloatware)"
echo "========================================="
echo "AVD Name: $AVD_NAME"
echo "System Image: $SYSTEM_IMAGE"
echo ""

# Check if system image is installed
echo "Checking if AOSP system image is installed..."
if ! "$SDKMANAGER" --list_installed 2>/dev/null | grep -q "$SYSTEM_IMAGE"; then
    echo "AOSP system image not found. Installing..."
    echo "y" | "$SDKMANAGER" "$SYSTEM_IMAGE"
    echo "✓ AOSP system image installed"
else
    echo "✓ AOSP system image already installed"
fi

# Create AVD
echo ""
echo "Creating AVD..."
if "$AVDMANAGER" list avd | grep -q "$AVD_NAME"; then
    echo "⚠️  AVD already exists. Deleting old one..."
    "$AVDMANAGER" delete avd -n "$AVD_NAME"
fi

echo "no" | "$AVDMANAGER" create avd \
    -n "$AVD_NAME" \
    -k "$SYSTEM_IMAGE" \
    -d "pixel_2" \
    --force

echo "✓ AVD created: $AVD_NAME"

# Configure AVD with optimized settings
AVD_CONFIG="$HOME/.android/avd/${AVD_NAME}.avd/config.ini"
echo ""
echo "Configuring AVD with optimized settings..."

if [ -f "$AVD_CONFIG" ]; then
    # Remove old RAM/GPU settings if they exist
    grep -v "^hw.ramSize" "$AVD_CONFIG" | \
    grep -v "^hw.gpu.enabled" | \
    grep -v "^vm.heapSize" > "${AVD_CONFIG}.tmp"

    mv "${AVD_CONFIG}.tmp" "$AVD_CONFIG"

    # Add optimized settings
    echo "hw.ramSize = 4096" >> "$AVD_CONFIG"
    echo "hw.gpu.enabled = yes" >> "$AVD_CONFIG"
    echo "vm.heapSize = 512" >> "$AVD_CONFIG"

    echo "✓ Configured with 4096 MB RAM, 512 MB heap"
else
    echo "⚠️  Config file not found: $AVD_CONFIG"
fi

# Show comparison
echo ""
echo "========================================="
echo "AVD Created Successfully!"
echo "========================================="
echo ""
echo "System Image Comparison:"
echo "------------------------"
echo "google_apis (old):    8.2 GB, 74 Google packages, 22 processes"
echo "aosp/default (new):   ~2 GB, 0 Google packages, ~5 processes"
echo ""
echo "To use this AVD, modify start_emulator.sh:"
echo "  Change SYSTEM_IMAGE from 'google_apis' to 'aosp'"
echo ""
echo "Or start it directly:"
echo "  SYSTEM_IMAGE=aosp ./start_emulator.sh"
echo ""
echo "Available AVDs:"
"$AVDMANAGER" list avd | grep "Name:"
echo ""
