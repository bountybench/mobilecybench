#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

rm -f "$SCRIPT_DIR/scores.json"

docker compose -f "$SCRIPT_DIR/docker-compose.yml" down -v