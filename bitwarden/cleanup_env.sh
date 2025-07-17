#!/bin/bash
set -e

echo "[INFO] Cleaning up environment..."
docker-compose down -v
echo "[INFO] Environment cleaned up."