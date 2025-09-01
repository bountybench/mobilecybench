#!/bin/bash
set -e

echo "Removing scores..."
rm -f scores.json

echo "Removing log files..."
rm -f fake_agent_log.log
rm -f *.log

echo "Taking down containers..."
docker compose down -v

echo "Cleanup complete"