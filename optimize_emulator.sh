#!/bin/bash
# Optimize emulator by disabling unnecessary Google bloatware

set -e

echo "=== Optimizing Android Emulator ==="
echo "This will disable unnecessary Google services to reduce ANR..."

# Wait for device
adb wait-for-device

# Dismiss any existing ANR dialogs
echo "Dismissing any ANR dialogs..."
adb shell input keyevent KEYCODE_BACK
adb shell input keyevent KEYCODE_BACK
sleep 1

# List of packages to disable (keeps only essential Google services)
BLOATWARE=(
    "com.google.android.youtube"
    "com.google.android.apps.youtube.music"
    "com.google.android.videos"
    "com.google.android.music"
    "com.google.android.apps.maps"
    "com.google.android.apps.photos"
    "com.google.android.apps.docs"
    "com.google.android.apps.messaging"
    "com.google.android.googlequicksearchbox"
    "com.google.android.apps.googleassistant"
    "com.google.android.as"
    "com.google.android.tts"
    "com.google.android.dialer"
    "com.google.android.calendar"
    "com.google.android.contacts"
    "com.google.android.apps.wellbeing"
    "com.android.chrome"
    "com.google.android.apps.turbo"
    "com.google.android.projection.gearhead"
)

echo "Disabling unnecessary packages..."
disabled_count=0
for package in "${BLOATWARE[@]}"; do
    if adb shell pm list packages | grep -q "^package:$package$"; then
        echo "  Disabling: $package"
        adb shell pm disable-user --user 0 "$package" 2>/dev/null && ((disabled_count++)) || echo "    (already disabled or failed)"
    fi
done

echo ""
echo "✓ Disabled $disabled_count packages"

# Force stop all Google apps to free memory immediately
echo ""
echo "Force stopping all Google apps..."
adb shell "for pkg in \$(pm list packages | grep google | cut -d: -f2); do am force-stop \$pkg 2>/dev/null; done"

# Clear logcat
echo "Clearing logcat..."
adb logcat -c

# Check memory after optimization
echo ""
echo "=== Memory Status After Optimization ==="
adb shell cat /proc/meminfo | grep -E "MemTotal|MemFree|MemAvailable"

echo ""
echo "=== Running Processes (Google) ==="
google_procs=$(adb shell ps -A | grep -E "google|gms|youtube" | wc -l)
echo "Google processes running: $google_procs (was 22)"

echo ""
echo "✓ Emulator optimization complete!"
echo ""
echo "IMPORTANT: These changes are temporary and will reset on next boot."
echo "To persist: Save an emulator snapshot after running this script."
