#!/bin/bash
set -e

echo "Removing secret files..."
rm -f secrets.sql
rm -f secrets.json

echo "Removing scores..."
rm -f scores.json

echo "Removing log files recursively..."
find . -type f -name "*.log" -delete

echo "Taking down containers..."
docker compose down