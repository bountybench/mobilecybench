#!/bin/bash

until adb connect host.docker.internal:5555; do
    echo "[KALI] Waiting for emulator connection"
    sleep 2
done

adb devices

cd talk-android
exec /bin/bash