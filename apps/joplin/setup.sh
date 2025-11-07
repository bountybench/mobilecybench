#!/bin/bash
set -e

echo "Running Docker compose..."
docker compose up --build -d

echo "Setting up app..."
./setup_app.sh