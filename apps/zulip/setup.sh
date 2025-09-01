#!/bin/bash
set -e

echo "Creating zulip-network"
docker network create zulip-network

echo "Starting Zulip containers with docker compose up"
docker compose up -d

echo "Add containers to zulip-network"
docker network connect zulip-network $(docker ps -q)

echo "Setup server"