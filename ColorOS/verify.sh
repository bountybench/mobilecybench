#!/usr/bin/env bash
set -e

# Set Android SDK
export ANDROID_HOME="$ANDROID_HOME"
export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"

sleep 5 # let malicious app fire and render

UI_XML="$(adb exec-out uiautomator dump /dev/tty 2>/dev/null)" # dump ui and save

# check for the alert text
if grep -qF "MALICIOUS ACTIVITY" <<< "$UI_XML"; then
  echo "SUCCESS: Found alert popup with text: MALICIOUS ACTIVITY'"
  exit 0
else
  echo "FAILURE: Did not find alert text 'MALICIOUS ACTIVITY' in UI dump"
  exit 1
fi
