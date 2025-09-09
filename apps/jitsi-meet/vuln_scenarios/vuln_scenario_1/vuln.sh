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

if docker network ls --format "{{.Name}}" | grep -q "^jitsi-network$"; then
  echo "[DEBUG] Removing docker network jitsi-network..."
  docker network rm jitsi-network
else
  echo "[DEBUG] No jitsi-network found."
fi


echo "All containers for Jitsi Meet have been killed."

exit 0
