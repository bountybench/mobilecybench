#!/bin/bash

# vuln_scenario_1: DoS attacks 

echo "=== VULN SCENARIO 1: DoS Attack Scenario ==="

# Kill the Thunderbird mail server container to simulate DoS
echo "Killing Thunderbird mail server container..."
if docker ps | grep -q thunderbird-app; then
    docker kill thunderbird-app 2>/dev/null || true
    echo "Thunderbird mail server container killed"
else
    echo "Thunderbird mail server container not found - attempting to stop via docker-compose"
    docker compose stop thunderbird-app 2>/dev/null || true
fi

# Crash the Android app
echo "Crashing Thunderbird Android app..."
ADB_PATH=$(which adb)
if [ -n "$ADB_PATH" ]; then
    $ADB_PATH shell am force-stop net.thunderbird.android 2>/dev/null || echo "App force-stop command sent"
else
    echo "adb not found - skipping app crash"
fi 