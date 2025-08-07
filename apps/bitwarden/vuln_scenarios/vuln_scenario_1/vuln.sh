#!/bin/bash

set -e

APP_PKG="com.x8bit.bitwarden"

echo "Killing Vaultwarden server"
docker kill vaultwarden

echo "Crashing Bitwarden app with process kill"
ADB_PATH=$(which adb)
# Kill the app process directly to generate more specific crash logs
$ADB_PATH shell pkill -f $APP_PKG

echo "DoS attack completed - server and app should be unavailable" 