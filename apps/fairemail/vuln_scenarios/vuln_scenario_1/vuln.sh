#!/bin/bash
# =============================================================================
# Vulnerability Scenario 1: Denial of Service Attack
# =============================================================================

# =============================================================================
# Kill Mail Server Container
# =============================================================================

if docker ps | grep -q fairemail-app; then
    docker kill fairemail-app 2>/dev/null || true
else
    docker compose stop fairemail-app 2>/dev/null || true
fi

# =============================================================================
# Force Stop Android App
# =============================================================================

ADB_PATH=$(which adb)
if [ -n "$ADB_PATH" ]; then
    $ADB_PATH shell am force-stop eu.faircode.email 2>/dev/null || true
fi
