#!/bin/bash

echo "Killing server"
docker kill radicale

echo "Crashing app"
ADB_PATH=$(which adb)

$ADB_PATH shell am crash at.bitfire.davdroid