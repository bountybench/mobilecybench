#!/bin/bash

set -e

PKG="${ANDROID_APP_PACKAGE:-com.nextcloud.talk2}"
SERVER_CONTAINER="${SERVER_CONTAINER:-nextcloud-server}"
TLS_PROXY_CONTAINER="${TLS_PROXY_CONTAINER:-nextcloud-talk-tls-proxy}"

echo "Killing server"
for container in "$SERVER_CONTAINER" "$TLS_PROXY_CONTAINER"; do
  if docker ps --filter "name=$container" --filter "status=running" -q | grep -q .; then
    docker kill "$container" || true
  else
    echo "Container $container is not running; skipping kill."
  fi
done

echo "Crashing app"
ADB_PATH=$(which adb || true)
if [ -z "$ADB_PATH" ]; then
  echo "adb not found; skipping app crash"
elif ! $ADB_PATH devices | awk 'NR>1 && $2=="device" {print $1}' | grep -q .; then
  echo "No Android device/emulator connected; skipping app crash"
else
  $ADB_PATH shell am crash "$PKG" || true
fi
