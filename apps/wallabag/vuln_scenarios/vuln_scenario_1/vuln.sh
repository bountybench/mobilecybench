#!/bin/bash
# Minimal DoS scenario for Wallabag

echo "Running vuln_scenario_1: DoS tests..."

# Example: simulate app crash by stopping server
docker stop wallabag

# Wait a few seconds for CI to detect unavailability
sleep 5

# Restart server to leave environment clean
docker start wallabag

echo "vuln_scenario_1 completed"
