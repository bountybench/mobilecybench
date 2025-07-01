#!/bin/bash
set -e

echo "[Entrypoint] Accessing Android emulator..."

export ADB_SERVER_SOCKET=tcp:host.docker.internal:5037
#adb connect host.docker.internal:5554
adb devices