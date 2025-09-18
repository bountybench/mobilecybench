#!/bin/bash
set -e

echo "Removing log files recursively..."
find . -type f -name "*.log" -delete

echo "Removing txt files recursively..."
find . -type f -name "*.txt" -delete

echo "Taking down containers..."
docker compose down

echo "Taking down shared_net..."
docker network rm shared_net