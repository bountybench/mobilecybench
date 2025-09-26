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


echo "All containers for Jitsi Meet have been killed."

exit 0
