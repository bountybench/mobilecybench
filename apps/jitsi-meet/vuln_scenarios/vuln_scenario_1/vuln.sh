#!/bin/bash

echo "Simulating DOS on Jitsi Meet..."

# Kill any leftover containers just in case
containers=$(docker ps --format "{{.Names}}")
if [ -n "$containers" ]; then
  echo "[DEBUG] Killing leftover containers..."
  for name in $containers; do
    docker kill "$name"
  done
fi

if docker network ls --format "{{.Name}}" | grep -q "^shared_net$"; then
  echo "[DEBUG] Removing docker network shared_net..."
  docker network rm shared_net
else
  echo "[DEBUG] No shared_net network found."
fi


echo "All containers for Jitsi Meet have been killed."

exit 0
