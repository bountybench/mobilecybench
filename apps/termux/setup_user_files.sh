#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Seeding realistic Termux private files from secrets.json..."

if [ ! -f "secrets.json" ]; then
    echo "Warning: secrets.json not found, skipping user environment setup"
    exit 0
fi

python3 probe_utils.py seed-device --secret-file secrets.json

echo "Seeded Termux home artifacts under /data/data/com.termux/files/home"
