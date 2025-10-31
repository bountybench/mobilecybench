#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# accounts.json is now a static file tracked in git, don't delete it
rm -f "$SCRIPT_DIR/scores.json"

docker compose -f "$SCRIPT_DIR/docker-compose.yml" down -v