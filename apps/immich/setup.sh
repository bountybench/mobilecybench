#!/bin/bash
# Main setup script for the Immich environment.

set -e
echo "🚀 Starting Immich setup..."

# 1. Install necessary dependencies (placeholder)
echo "[1/6] Checking dependencies..."
if ! command -v docker &> /dev/null || ! command -v docker-compose &> /dev/null; then
    echo "❌ Error: Docker and Docker-Compose are required."
    exit 1
fi
if ! command -v jq &> /dev/null; then
    echo "❌ Error: 'jq' is required for this script. Please install it (e.g., 'brew install jq')."
    exit 1
fi
echo "✅ Dependencies satisfied."

# 2. Generate UUIDs and store them in a temporary secret file
echo "[2/6] Generating secrets..."
SECRET_FILE=".secrets"
echo "AGENT_API_KEY=$(uuidgen)" > $SECRET_FILE
echo "✅ Secrets stored in '$SECRET_FILE'."

# 3. Download server configuration if it doesn't exist
if [ ! -f .env ]; then
    echo "[3/6] Downloading server .env configuration..."
    curl -L https://github.com/immich-app/immich/releases/latest/download/example.env -o .env
    sed -i.bak "s/^DB_PASSWORD=.*/DB_PASSWORD=postgres/" .env
    echo "✅ Server configuration downloaded."
else
    echo "[3/6] Server configuration already exists. Skipping download."
fi


# 4. Run docker-compose up for server/database
echo "[4/6] Starting Immich server via Docker Compose..."
docker network create shared_net || true
docker-compose up -d
echo "✅ Immich server is running in the background."

# 5. Wait for the server to initialize
echo "[5/6] Waiting 20 seconds for services to become healthy..."
sleep 20

# 6. Create the admin user programmatically
echo "[6/6] Creating admin user via Immich CLI..."
ADMIN_EMAIL=$(jq -r '.server.agent_username' metadata.json)
ADMIN_PASSWORD=$(jq -r '.server.agent_password' metadata.json)

# *** THIS IS THE NEW, CORRECTED COMMAND ***
# The main entry point is now index.js in the server's dist folder.
docker-compose exec -T immich-server node /usr/src/app/server/dist/index.js user create --email "$ADMIN_EMAIL" --password "$ADMIN_PASSWORD" --name admin

echo ""
echo "🎉 Setup complete! Admin user '$ADMIN_EMAIL' has been created."
echo "The server is fully ready for the agent at http://localhost:2283"