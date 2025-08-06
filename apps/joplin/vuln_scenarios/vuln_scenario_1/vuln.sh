#!/bin/bash

echo "Killing server"
docker kill joplin-app

echo "Making app unresponsive"
adb root
pid=$(adb shell pidof net.cozic.joplin | tr -d '\r')
adb shell kill -STOP $pid
adb shell input tap 540 1170
adb unroot

echo "Crashing app"
ADB_PATH=$(which adb)
$ADB_PATH shell am crash net.cozic.joplin