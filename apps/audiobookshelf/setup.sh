#!/bin/bash
set -e

# --- Configuration ---
ABS_URL="http://localhost:13378"
ADMIN_USERNAME="admin"
ADMIN_PASSWORD="DG*76ao%DC*&^<Ouidht"
LIBRARY_NAME="My Audiobooks"
LIBRARY_PATH="/audiobooks" # This MUST be the path inside the container

# pip install uiautomator2
# pip install psycopg2-binary
# pip install bcrypt

# echo "Generating uuids..."
# python generate_uuid.py

echo "Running Docker compose..."
docker compose up --build -d

echo "Waiting for Audiobookshelf server to be ready..."
# A simple wait loop to ensure the server is up before we send requests
until $(curl --output /dev/null --silent --head --fail "$ABS_URL"); do
    printf '.'
    sleep 2
done

echo "\nServer is up! Creating initial admin user..."

# Create the first user and capture the JSON response
RESPONSE_JSON=$(curl -s -X POST "$ABS_URL/setup" \
  -H "Content-Type: application/json" \
  -d "{\"username\": \"$ADMIN_USERNAME\", \"password\": \"$ADMIN_PASSWORD\"}")

echo "User '$ADMIN_USERNAME' created successfully."

# echo "Setting up app..."
./setup_app.sh