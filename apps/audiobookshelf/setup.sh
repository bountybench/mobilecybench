#!/bin/bash
set -e

# --- Configuration ---
ABS_URL="http://localhost:13378"
ADMIN_USERNAME="root"
ADMIN_PASSWORD="DG*76ao%DC*&^Ouidht"

echo "Running Docker compose..."
docker compose up --build -d

echo "Waiting for Audiobookshelf server to be ready..."
# A simple wait loop to ensure the server is up before we send requests
until $(curl --output /dev/null --silent --head --fail "$ABS_URL"); do
    printf '.'
    sleep 2
done

echo "\nServer is up! Creating initial admin user..."

# NOTE: Temorarily unused while the configuration loaded in ./files/ is being used
# Create the first user and capture the JSON response
# if curl -H "Content-Type: application/json" --request POST -d "{\"newRoot\": {\"username\": \"$ADMIN_USERNAME\", \"password\": \"$ADMIN_PASSWORD\"}}" --fail "$ABS_URL/init"; then
#   echo "User '$ADMIN_USERNAME' created."
# else
#   echo "Error in creating admin user."
# fi

# echo "Setting up app..."
# ./setup_app.sh