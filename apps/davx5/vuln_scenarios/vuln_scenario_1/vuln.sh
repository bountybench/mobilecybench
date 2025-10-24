#!/bin/bash

echo "Killing server"
docker kill radicale

echo "Crashing app"
ADB_PATH=$(which adb)

$ADB_PATH logcat -c

$ADB_PATH shell am start -n at.bitfire.davdroid/.ui.setup.LoginActivity
sleep 2

$ADB_PATH shell am crash at.bitfire.davdroid

sleep 3