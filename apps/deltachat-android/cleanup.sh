#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

rm -f "$SCRIPT_DIR/accounts.json"
rm -f "$SCRIPT_DIR/scores.json"

docker compose -f "$SCRIPT_DIR/docker-compose.yml" down -v
rm -rf "$SCRIPT_DIR/mail-data" "$SCRIPT_DIR/mail-state" "$SCRIPT_DIR/mail-logs"
