#!/bin/bash

echo "Resetting ownCloud environment..."

# Stop and remove containers completely
echo "Stopping and removing containers..."
docker compose down --remove-orphans
docker rm -f owncloud_server owncloud_mariadb owncloud_redis 2>/dev/null || true
docker container prune -f

# Remove persistent volumes (ignore errors if volumes don't exist)
echo "Removing volumes..."
docker volume rm owncloud-android_files owncloud-android_mysql owncloud-android_redis 2>/dev/null || true

# Start fresh environment
echo "Starting fresh environment..."
docker compose up -d

echo "Environment reset complete!"
echo "Access ownCloud at: http://localhost:8080"
echo "Access ownCloud From Emulator at: http://10.0.2.2:8080"
echo "Admin credentials: admin/admin"
