#!/bin/bash
set -e

echo "[Entrypoint] Accessing Android emulator..."

#export ADB_SERVER_SOCKET=tcp:host.docker.internal:5037
export ADB_SERVER_SOCKET=tcp:localhost:5037
export ADB_TRACE=all
adb devices

# If arguments are provided, execute them with bash
if [ $# -gt 0 ]; then
    exec bash "$@"
else
    # Default behavior if no arguments
    exec bash
fi