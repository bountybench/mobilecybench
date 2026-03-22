#!/bin/bash

export MSYS_NO_PATHCONV=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Clearing logcat..."
adb shell logcat -c

echo "Clearing Jitsi image cache..."
adb shell rm -rf //data/data/org.jitsi.meet/cache/image_cache/ 2>/dev/null || true

echo "Preparation complete."