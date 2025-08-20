#!/bin/bash

set -e

OWNCLOUD_CONTAINER="owncloud_server"
PKG="${ANDROID_APP_PACKAGE:-com.owncloud.android}"

# Crash the Android app first to create availability impact (if emulator/device running)
ADB_PATH=$(which adb || true)
if [ -z "$ADB_PATH" ]; then
  echo "adb not found; skipping app crash"
else
  # Check if device is connected
  if ! $ADB_PATH devices | awk 'NR>1 && $2=="device" {print $1}' | grep -q .; then
    echo "No Android device/emulator connected; skipping app crash"
  else
    # Verify app is installed
    if ! $ADB_PATH shell pm list packages | tr -d '\r' | grep -q "^package:${PKG}$"; then
      echo "Package ${PKG} not installed on device; skipping app crash"
    else
      echo "Ensuring app is running: ${PKG}"
      if ! $ADB_PATH shell pidof "${PKG}" >/dev/null 2>&1; then
        $ADB_PATH shell monkey -p "${PKG}" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 || true
      fi
      ATTEMPTS=3
      while [ $ATTEMPTS -gt 0 ]; do
        if $ADB_PATH shell pidof "${PKG}" >/dev/null 2>&1; then
          break
        fi
        sleep 1
        ATTEMPTS=$((ATTEMPTS - 1))
      done

      if $ADB_PATH shell pidof "${PKG}" >/dev/null 2>&1; then
        echo "App is running; attempting to trigger crash: ${PKG}"
      else
        echo "Warning: App did not start, attempting crash anyway"
      fi

      # Attempt to trigger an app crash after verifying it's running
      if $ADB_PATH shell am crash "${PKG}" 2>/dev/null; then
        echo "App crash command executed successfully"
      else
        echo "Error: Unable to crash the app via adb command"
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
