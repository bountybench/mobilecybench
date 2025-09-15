#!/bin/bash
set -e

# --- Configuration ---
ABS_URL="http://localhost:13378"
ADMIN_USERNAME="admin"
ADMIN_PASSWORD="DG*76ao%DC*&^<Ouidht"

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
# ./setup_app.sh