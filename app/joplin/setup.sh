#!/bin/bash
set -e

pip install uiautomator2
pip install psycopg2-binary
pip install bcrypt
export JOPLIN_DIR=$(pwd)
echo $JOPLIN_DIR

echo "Generating uuids..."
python generate_uuid.py

ls -l ${JOPLIN_DIR}/seed.sql
ls -l ${JOPLIN_DIR}/secrets.sql

echo "Running Docker compose..."
docker compose up --build -d

pwd
ls

echo "Viewing seeder logs"
docker compose logs seeder

echo "Setting up app..."
./setup_app_apklink.sh