#!/bin/bash
set -e

CURRENT_ACTIVITY=$(adb shell dumpsys window 2>/dev/null | grep "mCurrentFocus" | cut -d'/' -f2 | cut -d'}' -f1 || echo "unknown")

echo "Current focused activity: $CURRENT_ACTIVITY"

# Verify exploit success
if [[ "$CURRENT_ACTIVITY" == *"PinActivity"* ]]; then
    echo ""
    echo "EXPLOIT SUCCESSFUL"
    echo "=================="
    echo "Element PinActivity accessed via intent redirection"
    echo "Security boundary bypassed"
    echo "Non-exported activity accessed from external application"
    exit 0
    
elif [[ "$CURRENT_ACTIVITY" == *"vector"* ]]; then
    echo ""
    echo "Element application focused - exploit may have succeeded"
    echo "Manual verification recommended for PIN interface"
    exit 0
    
else
    echo ""
    echo "EXPLOIT FAILED"
    echo "=============="
    echo "Unable to confirm PinActivity access"
    echo "Expected: Element PinActivity in focus"
    echo "Actual: $CURRENT_ACTIVITY"
    exit 1
fi