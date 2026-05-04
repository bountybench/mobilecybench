#!/bin/bash

set -e

SERVER_CONTAINER="${SERVER_CONTAINER:-nextcloud-server}"
TLS_PROXY_CONTAINER="${TLS_PROXY_CONTAINER:-nextcloud-talk-tls-proxy}"

echo "Killing server"
for container in "$SERVER_CONTAINER" "$TLS_PROXY_CONTAINER"; do
  if docker ps --filter "name=$container" --filter "status=running" -q | grep -q .; then
    docker kill "$container" || true
  else
    echo "Container $container is not running; skipping kill."
  fi
done
