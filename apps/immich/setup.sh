#!/bin/bash
set -e
echo "🚀 Starting Immich setup..."
echo "[1/4] Checking dependencies..."
if ! command -v docker &> /dev/null || ! command -v docker-compose &> /dev/null; then
    echo "❌ Error: Docker and Docker-Compose are required."
    exit 1
fi
echo "✅ Dependencies satisfied."
echo "[2/4] Generating secrets..."
SECRET_FILE=".secrets"
echo "AGENT_API_KEY=$(uuidgen)" > $SECRET_FILE
echo "✅ Secrets stored in '$SECRET_FILE'."
if [ ! -f .env ]; then
    echo "[3/4] Downloading server .env configuration..."
    curl -L https://github.com/immich-app/immich/releases/latest/download/example.env -o .env
    sed -i.bak "s/^DB_PASSWORD=.*/DB_PASSWORD=postgres/" .env
    echo "✅ Server configuration downloaded."
else
    echo "[3/4] Server configuration already exists. Skipping download."
fi
echo "[4/4] Starting Immich server via Docker Compose..."
docker network create shared_net || true
docker-compose up -d
echo "✅ Immich server is running in the background."
echo "Login at http://localhost:2283"