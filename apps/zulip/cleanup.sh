#!/bin/bash
set -e

echo "docker compose down"
docker compose down

# Remove the zulip-network and then remove all live containers
docker network rm zulip-network
docker container prune -f