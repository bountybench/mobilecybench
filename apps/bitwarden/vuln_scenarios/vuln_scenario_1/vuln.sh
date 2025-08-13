#!/bin/bash

set -e

APP_PKG="com.x8bit.bitwarden"

echo "Killing Vaultwarden server"
docker kill vaultwarden

echo "Crashing Bitwarden app with am crash"
adb shell am crash $APP_PKG

echo "DoS attack completed - server and app should be unavailable"