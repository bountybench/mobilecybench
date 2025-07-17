#!/bin/bash
set -e

# Start Docker containers for server and database
echo "[INFO] Starting Docker containers for Vaultwarden server and PostgreSQL database..."
docker-compose up --build -d
echo "[INFO] Docker containers started."