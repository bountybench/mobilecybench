#!/bin/bash
set -e

echo "[Entrypoint] Connecting to Android emulator..."

adb connect localhost:5554
adb devices

echo "[Entrypoint] Running passed command: $@"
exec "$@"
