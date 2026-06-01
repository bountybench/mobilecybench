#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"

# `set -a` so env vars also reach the python child (probe_lib imports
# common_setup, which does require_env at module load).
ENV_FILE="$SCRIPT_DIR/benchmark.env"
if [ ! -f "$ENV_FILE" ]; then
    ENV_FILE="$SCRIPT_DIR/.env"
fi
set -a
source "$ENV_FILE"
set +a

VICTIM_USER="${1:-admin}"
PASS_VAR="$(printf '%s' "$VICTIM_USER" | tr '[:lower:]' '[:upper:]')_PASSWORD"
VICTIM_PASS="${!PASS_VAR:?Password env var $PASS_VAR not set in $ENV_FILE}"

log_info "Logging in $VICTIM_USER on Nextcloud Talk"
python3 "$SCRIPT_DIR/ui_automation/login.py" \
    --username "$VICTIM_USER" \
    --password "$VICTIM_PASS"

# login.py returns once the conversation list UI appears, but Talk's
# room-sync RPC is still in flight. Block until rows are in the DB so
# downstream consumers (probes, vuln.sh-style harness steps) don't race.
if [ "$VICTIM_USER" = "admin" ]; then
    log_info "Waiting for Talk room sync"
    PYTHONPATH="$SCRIPT_DIR/../..:${PYTHONPATH:-}" python3 \
        "$SCRIPT_DIR/ui_automation/wait_for_room_sync.py"
fi

log_info "prepare_victim.sh complete"
