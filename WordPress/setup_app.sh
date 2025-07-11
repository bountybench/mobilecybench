#!/usr/bin/env bash

# variables
REPO_DIR="WordPress-Android"
APK_REL="WordPress/build/outputs/apk/wordpressVanilla/debug/org.wordpress.android-wordpress-vanilla-debug.apk"
APK_PATH="$REPO_DIR/$APK_REL"
AVD_NAME="Pixel_2_API_28"
WP_SITE_URL="10.0.2.2:8000"
WP_USER="user_a"
WP_PASS="user_a_pass"
export PATH="$HOME/.android-sdk/platform-tools:$PATH"

wait_for_boot() {
  echo -n "   ⏳ waiting for sys.boot_completed…"
  until adb shell getprop sys.boot_completed 2>/dev/null | grep -q "^1$"; do
    printf "."
    sleep 0.5
  done
}

wait_for_activity() {
  local ACT="$1"
  echo -n "   ⏳ waiting for activity ${ACT}…"
  until adb shell dumpsys activity activities \
      | grep -q "mResumedActivity.*${ACT}"; do
    printf "."
    sleep 0.3
  done
}

echo "1/6 building WordPress APK"
cd "$REPO_DIR"
#./gradlew clean assembleVanillaDebug -x lint
cd ..

echo "1/6 starting emulator"
../start_emulator.sh "$AVD_NAME" &
adb wait-for-device
wait_for_boot

echo "2/6 installing and launching APK"
adb install -r "$APK_PATH"
adb shell am start \
  -n org.wordpress.android/.ui.WPLaunchActivity \
  -a android.intent.action.MAIN \
  --ez android.intent.extra.ALLOW_MULTIPLE false \
  --es wp_site_url "$WP_SITE_URL"
wait_for_activity "WPLaunchActivity"

echo "3/6 click login button"
adb shell input keyevent 61
adb shell input keyevent 61
adb shell input keyevent 61
adb shell input keyevent 66

echo "4/6 entering site URL"
adb shell input text "$WP_SITE_URL"
adb shell input keyevent 66
sleep 3

echo "5/6 entering username"
adb shell input text "$WP_USER"
adb shell input keyevent 61

echo "6/6 entering password"
adb shell input text "$WP_PASS"
adb shell input keyevent 66