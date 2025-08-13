#!/bin/bash
set -e

pip install uiautomator2
pip install psycopg2-binary
pip install bcrypt

echo "Generating uuids..."
python generate_uuid.py

echo "Running Docker compose..."
docker compose up --build -d

echo "Setting up app..."
./setup_app_apklink.sh