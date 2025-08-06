#!/bin/bash
set -e

# Check for --dump flag
DUMP_FLAG=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --dump)
            DUMP_FLAG=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# echo "[INFO] Removing secret files..."
rm flags.json || true
rm secrets.json || true
rm codebase/user.properties || true

# Remove dump.sql if --dump flag is provided
if [ "$DUMP_FLAG" = true ]; then
    echo "[INFO] Removing dump.sql (--dump flag provided)..."
    rm dump.sql || true
fi

echo "[INFO] Removing evaluating files..."
rm scores.json || true

echo "[INFO] Removing agent log..."
rm agent_log.log || true

echo "[INFO] Removing vw-data directory..."
rm -rf vw-data || true

echo "[INFO] Removing apk files"
rm bitwarden.apk || true

echo "[INFO] Cleaning up environment..."
docker compose down -v
echo "[INFO] Environment cleaned up."