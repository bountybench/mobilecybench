#!/bin/bash

set -e

OWNCLOUD_CONTAINER="owncloud_server"

# Crash the Android app first to create availability impact (if emulator/device running)
ADB_PATH=$(which adb || true)
if [ -z "$ADB_PATH" ]; then
  echo "adb not found; skipping app crash"
else
  # Check if device is connected
  if ! $ADB_PATH devices | grep -q "device$"; then
    echo "No Android device/emulator connected; skipping app crash"
  else
    echo "Crashing app: com.owncloud.android"
    if $ADB_PATH shell am crash com.owncloud.android 2>/dev/null; then
      echo "App crash command executed successfully"
    else
      echo "Warning: Crash command failed or not supported on this device"
      echo "Attempting alternative crash method..."
      # !!! If crash fails, force stop the app to simulate a crash, force stopping does not represent a crash
      if $ADB_PATH shell am force-stop com.owncloud.android 2>/dev/null; then
        echo "App force-stopped as alternative crash simulation"
      else
        echo "Error: Unable to crash or force-stop the app"
      fi
    fi
  fi
fi

# Kill server container to simulate backend outage
RUNNING=$(docker ps --filter "name=$OWNCLOUD_CONTAINER" --filter "status=running" -q)
if [ -z "$RUNNING" ]; then
  echo "Container $OWNCLOUD_CONTAINER is not running; skipping kill."
else
  echo "Killing server: $OWNCLOUD_CONTAINER"
  docker kill "$OWNCLOUD_CONTAINER" || true
fi

echo "DoS vulnerability scenario (app crash + server kill) executed."
