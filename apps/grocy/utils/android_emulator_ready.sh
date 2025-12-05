#!/bin/bash
# Simplified android_emulator_ready.sh for Grocy
# Grocy's vuln_scenario_0 doesn't require /system modifications,
# so we make this script more tolerant of remount failures

set -e

echo "=== Running android_emulator_ready.sh ==="

# Step 1: Wait for device boot
echo "==> Starting 1) Boot sequence"
echo "Waiting for boot_completed/dev.bootcomplete + compositor..."

adb wait-for-device

# Wait for boot to complete
timeout=300
elapsed=0
while [ $elapsed -lt $timeout ]; do
    boot_completed=$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')
    if [ "$boot_completed" = "1" ]; then
        break
    fi
    sleep 1
    elapsed=$((elapsed + 1))
done

echo "<== 1) Boot sequence finished in ${elapsed}s"

# Step 2: Root and remount (optional for Grocy)
if [ "$1" = "--remount" ]; then
    echo "==> Starting 2) Root + disable verification + remount"
    echo "Requesting root..."

    # Try to get root, but don't fail if it doesn't work
    adb root 2>/dev/null || echo "Root request completed"

    # Wait for device to reconnect
    sleep 2
    adb wait-for-device || true

    # Get SDK version
    sdk=$(adb shell getprop ro.build.version.sdk 2>/dev/null | tr -d '\r')
    echo "Device SDK = $sdk"

    # Try to disable verification and remount, but don't fail if it doesn't work
    # Grocy's CSRF exploit doesn't need /system modifications
    echo "Disabling AVB verification (avbctl)..."
    if adb shell avbctl disable-verification 2>/dev/null; then
        echo "Successfully disabled verification. Reboot the device for changes to take effect."
        echo "Rebooting after verification change..."
        adb reboot || true
        sleep 5
        adb wait-for-device || true

        # Wait for boot to complete again
        timeout=300
        elapsed=0
        while [ $elapsed -lt $timeout ]; do
            boot_completed=$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')
            if [ "$boot_completed" = "1" ]; then
                break
            fi
            sleep 1
            elapsed=$((elapsed + 1))
        done

        echo "INFO         | Boot completed in ${elapsed} ms"
        echo "INFO         | Increasing screen off timeout, logcat buffer size to 2M."
        adb shell settings put system screen_off_timeout 2147483647 2>/dev/null || true
        adb logcat -G 2M 2>/dev/null || true

        # Try to remount but don't fail if it doesn't work
        echo "Remounting /system (overlayfs expected on API 29+)..."
        if ! adb root 2>/dev/null; then
            echo "Warning: Could not re-acquire root after reboot, but continuing anyway"
            echo "Grocy vuln_scenario_0 doesn't require /system modifications"
        else
            adb remount 2>/dev/null || echo "Warning: Remount failed, but continuing anyway (not required for Grocy)"
        fi
    else
        echo "Warning: Could not disable AVB verification, but continuing anyway"
        echo "Grocy vuln_scenario_0 doesn't require /system modifications"
    fi

    echo "<== 2) Root + remount step completed (with warnings allowed)"
else
    echo "No --remount flag, skipping root/remount steps"
fi

echo "=== android_emulator_ready.sh completed successfully ==="
exit 0
