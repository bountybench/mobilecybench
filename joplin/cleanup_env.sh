#!/bin/bash
set -e

echo "Removing secret files..."
rm -f secrets.sql
rm -f secrets.json

echo "Taking down containers..."
docker compose down