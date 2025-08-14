#!/bin/bash

echo "Killing server"
docker kill joplin-app

echo "Crashing app"
ADB_PATH=$(which adb)
$ADB_PATH shell am crash net.cozic.joplin