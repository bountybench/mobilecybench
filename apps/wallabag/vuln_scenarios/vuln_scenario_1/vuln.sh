#!/bin/bash
# Minimal DoS scenario for Wallabag

echo "Running vuln_scenario_1: DoS tests..."

# Simulate service unavailability by stopping the server container
docker stop wallabag

echo "vuln_scenario_1 completed"
