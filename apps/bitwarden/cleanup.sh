#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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
rm "$SCRIPT_DIR/flags.json" || true
rm "$SCRIPT_DIR/secrets.json" || true
rm "$SCRIPT_DIR/codebase/user.properties" || true

# Remove dump.sql if --dump flag is provided
if [ "$DUMP_FLAG" = true ]; then
    echo "[INFO] Removing dump.sql (--dump flag provided)..."
    rm "$SCRIPT_DIR/dump.sql" || true
fi

echo "[INFO] Removing evaluating files..."
rm "$SCRIPT_DIR/scores.json" || true

echo "[INFO] Removing agent log..."
rm "$SCRIPT_DIR/vuln_scenarios/vuln_scenario_0/agent_log.log" || true

echo "[INFO] Removing apk files"
rm "$SCRIPT_DIR/bitwarden.apk" || true

echo "[INFO] Cleaning up environment..."
docker compose down -v
echo "[INFO] Environment cleaned up."