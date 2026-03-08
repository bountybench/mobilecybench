#!/bin/bash

# Standardized run_checks.sh for Bitwarden
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$APP_DIR/../../" && pwd)"
exploit_log="$1"

# Use the universal root run_checks.sh
# It will call test_access_control.py, test_availability.py, etc.
# in the app directory.
bash "$ROOT_DIR/run_checks.sh" "$APP_DIR" "$exploit_log"
