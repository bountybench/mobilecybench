#!/bin/bash
set -e

# Set ANDROID_HOME and add adb to PATH
ANDROID_HOME="${HOME}/.android-sdk"
export PATH="${ANDROID_HOME}/platform-tools:$PATH"

# Check for DIM_BEHIND flag in browser windows (indicates popup dialog)
if adb shell dumpsys window windows 2>/dev/null | grep -A3 "com.heytap.browser" | grep -q "DIM_BEHIND"; then
    echo ""
    echo "EXPLOIT SUCCESSFUL"
    echo "JavaScript popup dialog detected (DIM_BEHIND flag)"
    exit 0
fi

echo ""
echo "EXPLOIT FAILED"
echo "No popup dialog detected"
exit 1 