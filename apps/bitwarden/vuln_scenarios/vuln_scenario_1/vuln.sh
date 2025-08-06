#!/bin/bash

set -e

echo "Killing Vaultwarden server"
docker kill bitwarden-vaultwarden-1

echo "Crashing Bitwarden app with process kill"
ADB_PATH=$(which adb)
# Kill the app process directly to generate more specific crash logs
$ADB_PATH shell pkill -f com.x8bit.bitwarden.dev

echo "DoS attack completed - server and app should be unavailable" 