#!/bin/bash

set -e

OWNCLOUD_CONTAINER="owncloud_server"

# Check if container is running
RUNNING=$(docker ps --filter "name=$OWNCLOUD_CONTAINER" --filter "status=running" -q)
if [ -z "$RUNNING" ]; then
  echo "Container $OWNCLOUD_CONTAINER is not running; skipping kill."
else
  echo "Killing server: $OWNCLOUD_CONTAINER"
  docker kill "$OWNCLOUD_CONTAINER"
fi

ADB_PATH=$(which adb)
if [ -z "$ADB_PATH" ]; then
  echo "adb not found; skipping app crash"
  exit 0
fi
echo "Crashing app: com.owncloud.android"
$ADB_PATH shell am crash com.owncloud.android || echo "Crash command not supported; try ANR trigger manually."
