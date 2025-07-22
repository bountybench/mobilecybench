#!/bin/bash
set -e

echo "Removing secret files..."
rm -f initdb/accounts.sql
rm -f accounts.json
rm -f logins.txt

echo "[INFO] Cleaning up environment..."
docker-compose down -v
echo "[INFO] Environment cleaned up."

rm -rf vw-data

rm -f bitwarden_db_dump.sql