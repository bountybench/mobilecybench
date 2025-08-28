#!/bin/bash
set -e

docker compose up --build -d

echo "Setting up app..."
./setup_app.sh