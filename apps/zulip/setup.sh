#!/bin/bash
set -e

echo "Creating zulip-network"
docker network create zulip-network

echo "Starting Zulip containers with docker compose up"
docker compose up -d

echo "Add containers to zulip-network"
for cid in $(docker ps -q); do
  docker network connect zulip-network $cid
done

echo "Server is set up."

echo "Setup app"

chmod +x setup_app.sh
./setup_app.sh

echo "App is set up."

echo "Done."