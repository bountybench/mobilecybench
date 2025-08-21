#!/bin/bash
set -e

pip install uiautomator2
pip install psycopg2-binary
pip install bcrypt

free -h
df -h

echo "Generating uuids..."
python generate_uuid.py

free -h
df -h

echo "Running Docker compose..."
docker compose up --build -d

free -h
df -h

echo "Setting up app..."
./setup_app.sh