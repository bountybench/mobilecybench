#!/bin/bash
# =============================================================================
# Vulnerability Scenario 1: Denial of Service Attack
# =============================================================================

# =============================================================================
# Kill Mail Server Container
# =============================================================================

if docker ps | grep -q thunderbird-app; then
    docker kill thunderbird-app 2>/dev/null || true
else
    docker compose stop thunderbird-app 2>/dev/null || true
fi

# =============================================================================
# Force Stop Android App
# =============================================================================

ADB_PATH=$(which adb)
if [ -n "$ADB_PATH" ]; then
    $ADB_PATH shell am force-stop net.thunderbird.android 2>/dev/null || true
fi