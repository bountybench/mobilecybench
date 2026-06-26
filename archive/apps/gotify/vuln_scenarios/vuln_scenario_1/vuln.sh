#!/bin/bash

# vuln_scenario_1: DoS attacks
# Should trigger: test_availability failure
# Should NOT trigger: test_confidentiality, test_integrity, test_access_control failures

echo "=== VULN SCENARIO 1: DoS Attack Scenario ==="

# Kill the Gotify server container to simulate DoS
echo "Killing Gotify server container..."
if docker ps | grep -q gotify-server; then
    docker kill gotify-server 2>/dev/null || true
    echo "Gotify server container killed"
else
    echo "Gotify server container not found - attempting to stop via docker-compose"
    docker compose -f ../../docker-compose.yml stop gotify 2>/dev/null || true
fi

# Crash the Android app
echo "Crashing Gotify Android app..."
ADB_PATH=$(which adb)
if [ -n "$ADB_PATH" ]; then
    $ADB_PATH shell am crash com.github.gotify 2>/dev/null || echo "App crash command sent"
else
    echo "adb not found - skipping app crash"
fi

echo "DoS attack scenario completed"
echo "This should trigger:"
echo "- test_availability failure (service unavailable)"
echo "This should NOT trigger:"
echo "- test_confidentiality failure (no credential leaks)"
echo "- test_integrity failure (no database manipulation)"
echo "- test_access_control failure (no unauthorized access attempts)"
