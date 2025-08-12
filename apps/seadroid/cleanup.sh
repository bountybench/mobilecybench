#!/usr/bin/env bash

# Remove volumes
rm -rf seadoc-data
rm -rf seafile-caddy
rm -rf seafile-data
rm -rf seafile-mysql
echo "Removed old volumes..."

docker compose down -v
echo "Stopped the server..."