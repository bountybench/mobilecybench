#!/bin/bash
set -e

echo "Generating uuids..."
python generate_uuid.py

echo "Running Docker compose..."
docker compose up --build -d