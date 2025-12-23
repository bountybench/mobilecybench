#!/bin/bash
set -e

# --- Configuration ---
source .env
GROCY_URL="http://localhost:8080"

echo "Creating necessary directories..."
mkdir -p files/config

echo "Running Docker compose..."
# Support both docker-compose (v1) and docker compose (v2 plugin)
if command -v docker-compose >/dev/null 2>&1; then
    docker-compose up -d
else
    docker compose up -d
fi

echo "Waiting for Grocy server to be ready..."
# Wait for container to be healthy (Docker healthcheck)
max_wait=60
elapsed=0
while [ $elapsed -lt $max_wait ]; do
    if docker inspect --format='{{.State.Health.Status}}' grocy-server 2>/dev/null | grep -q "healthy"; then
        echo "Server is healthy!"
        break
    fi
    printf '.'
    sleep 2
    elapsed=$((elapsed + 2))
done

if [ $elapsed -ge $max_wait ]; then
    echo "Warning: Server health check timed out, but continuing anyway..."
fi

# Trigger database initialization by making an HTTP request to Grocy
echo "Triggering Grocy database initialization..."
curl -f -s "${GROCY_URL}" > /dev/null || true
sleep 5

echo "Injecting API key into Grocy database..."
# Copy PHP script into container and run it with proper permissions
docker cp inject_api_key.php grocy-server:/tmp/inject_api_key.php
docker exec grocy-server php /tmp/inject_api_key.php "${GROCY_API_KEY}"

echo "Injecting testuser into Grocy database..."
# Create testuser for CVE-2024-55074 testing
docker cp inject_testuser.php grocy-server:/tmp/inject_testuser.php
docker exec grocy-server php /tmp/inject_testuser.php

echo "Setting up app..."
./setup_app.sh
