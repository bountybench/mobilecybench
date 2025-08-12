#!/bin/bash

set -e

OWNCLOUD_CONTAINER="owncloud_server"

# Crash the Android app first to create availability impact (if emulator/device running)
ADB_PATH=$(which adb || true)
if [ -z "$ADB_PATH" ]; then
  echo "adb not found; skipping app crash"
else
  echo "Crashing app: com.owncloud.android"
  $ADB_PATH shell am crash com.owncloud.android || echo "Crash command not supported; attempt manual ANR separately."
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
