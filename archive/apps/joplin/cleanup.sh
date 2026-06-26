#!/bin/bash
set -e

echo "Removing scores..."
rm -f scores.json

echo "Removing log files recursively..."
find . -type f -name "*.log" -delete
find vuln_scenarios -name "fake_agent_log.log" -delete 2>/dev/null || true

echo "Removing txt files recursively..."
find . -type f -name "*.txt" -delete

echo "Taking down containers..."
docker compose down