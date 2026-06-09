#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Seeding deterministic Termux golden-path artifacts..."
if ! adb shell su 0 test -f /data/local/tmp/mcb_termux_setup_anchor >/dev/null 2>&1; then
    python3 probe_utils.py create-anchor >/dev/null
fi
if [ -f "secrets.json" ]; then
    python3 probe_utils.py seed-device --secret-file secrets.json
else
    python3 probe_utils.py seed-device
fi

FLAGS_JSON="$SCRIPT_DIR/../../flags.json"
if [ -f "$FLAGS_JSON" ]; then
    echo "Injecting Termux app flag from flags.json..."
    PYTHONPATH="$SCRIPT_DIR/../..${PYTHONPATH:+:$PYTHONPATH}" python3 "$SCRIPT_DIR/../../utils/flag_injection_utils.py" --package com.termux
fi

echo "Seeded Termux private and shared artifacts for the controlled-online flow; manifest stored at /data/local/tmp/mcb_termux_seed_manifest.json"
