#!/usr/bin/env bash

# Remove old volumes
rm -rf seadoc-data
rm -rf seafile-caddy
rm -rf seafile-data
rm -rf seafile-mysql
echo "Removed old volumes..."

# Shutdown server
docker compose down -v
echo "Stopped the server..."