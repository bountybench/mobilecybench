#!/bin/bash
set -e

export ADB_SERVER_SOCKET=tcp:localhost:5037
adb devices
exec bash "$@"