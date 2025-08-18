#!/bin/bash
set -e

pip install uiautomator2
pip install psycopg2-binary
pip install bcrypt

echo "Generating uuids..."
python generate_uuid.py

echo "Running Docker compose..."
docker compose up --build -d

echo "Viewing seeder logs"
docker compose logs joplin-seeder-1

echo "inspecting joplin-seeder-1..."
docker inspect joplin-seeder-1

echo "Setting up app..."
./setup_app_apklink.sh