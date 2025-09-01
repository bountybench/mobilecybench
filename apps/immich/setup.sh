#!/bin/bash
# Streamlined setup script that starts the Immich server with existing data.

set -e
echo "🚀 Starting Immich setup..."

# 1. Check dependencies
echo "[1/3] Checking dependencies..."
if ! command -v docker &> /dev/null || ! command -v docker-compose &> /dev/null; then
    echo "❌ Error: Docker and Docker-Compose are required."
    exit 1
fi
echo "✅ Dependencies satisfied."

# 2. Download server configuration if it doesn't exist
if [ ! -f .env ]; then
    echo "[2/3] Downloading server .env configuration..."
    curl -L https://github.com/immich-app/immich/releases/latest/download/example.env -o .env
    sed -i.bak "s/^DB_PASSWORD=.*/DB_PASSWORD=postgres/" .env
    echo "✅ Server configuration downloaded."
else
    echo "[2/3] Server configuration already exists. Skipping download."
fi


# 3. Run docker-compose up for server/database
echo "[3/3] Starting Immich server via Docker Compose..."
docker network create shared_net || true
docker-compose up -d

echo ""
echo "🎉 Setup complete! The server is running with its existing data."
echo "Access it at http://localhost:2283"