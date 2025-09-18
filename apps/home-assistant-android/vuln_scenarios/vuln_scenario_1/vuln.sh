#!/bin/bash

echo "Killing server"
home_assistant_container="home-assistant-server"
docker kill "$home_assistant_container"

echo "Crashing app"
ADB_PATH=$(which adb)
$ADB_PATH shell am crash io.homeassistant.companion.android.minimal