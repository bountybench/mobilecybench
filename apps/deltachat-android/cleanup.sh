#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[INFO] Removing secret files..."
rm -f "$SCRIPT_DIR/accounts.json"
rm -f "$SCRIPT_DIR/secrets.json"

echo "[INFO] Removing evaluating files..."
rm -f "$SCRIPT_DIR/scores.json"

echo "[INFO] Removing apk files"
rm -f "$SCRIPT_DIR/deltachat.apk"

echo "[INFO] Cleaning up environment..."
docker compose -f "$SCRIPT_DIR/docker-compose.yml" down -v

echo "[INFO] Removing mail server data..."
rm -rf "$SCRIPT_DIR/mail-data" "$SCRIPT_DIR/mail-state" "$SCRIPT_DIR/mail-logs"

echo "[INFO] Environment cleaned up."
