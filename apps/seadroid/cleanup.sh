#!/usr/bin/env bash

# Remove volumes
rm -rf seadoc-data
rm -rf seafile-caddy
rm -rf seafile-data
rm -rf seafile-mysql

# Stop the emulator andserver
../stop_emulator.sh
sleep 1.5

docker compose down -v