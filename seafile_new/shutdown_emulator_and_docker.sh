#!/usr/bin/env bash

# Stop emulator 
./../stop_emulator.sh
sleep 1.5

# Stop docker
docker compose down -v