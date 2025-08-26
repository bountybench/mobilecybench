#!/bin/bash

echo "Killing server"
docker compose stop caddy

echo "Crashing app"
adb shell am crash com.seafile.seadroid2