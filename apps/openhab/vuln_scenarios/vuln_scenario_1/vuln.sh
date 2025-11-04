#!/bin/bash

set -e

APP_PKG="org.openhab.habdroid.beta"

echo "Killing OpenHAB server"
docker kill openhab

echo "Crashing OpenHAB app"
ADB_PATH=$(which adb)
$ADB_PATH shell am crash $APP_PKG

echo "DoS attack completed - server and app should be unavailable"