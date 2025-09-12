#!/usr/bin/env bash
set -e
echo "[init] Restoring initial snapshot into $POSTGRES_DB..."
if [ -f /docker-entrypoint-initdb.d/dev_seed.dump ]; then
  pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" /docker-entrypoint-initdb.d/dev_seed.dump
else
  echo "[init] No dev_seed.dump found; skipping restore."
fi
