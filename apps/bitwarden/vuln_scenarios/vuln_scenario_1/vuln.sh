#!/bin/bash

set -e

APP_PKG="com.x8bit.bitwarden"

echo "Killing Vaultwarden server"
docker kill vaultwarden

echo "Crashing Bitwarden app with idempotent force-stop"
adb shell am force-stop $APP_PKG

echo "DoS attack completed - server and app should be unavailable" 