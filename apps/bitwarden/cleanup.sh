#!/bin/bash
set -e

# echo "[INFO] Removing secret files..."
rm flags.json || true
rm secrets.json || true
rm dump.sql || true
rm codebase/user.properties || true

echo "[INFO] Removing evaluating files..."
rm scores.json || true

echo "[INFO] Removing agent log..."
rm agent_log.log || true

echo "[INFO] Removing vw-data directory..."
rm -rf vw-data || true

echo "[INFO] Removing apk files"
rm bitwarden.apk || true

echo "[INFO] Cleaning up environment..."
docker-compose down -v
echo "[INFO] Environment cleaned up."