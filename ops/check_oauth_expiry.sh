#!/bin/bash
# Check Claude Code OAuth token expiry from macOS Keychain.
# Exit 0 = OK (>2hr remaining), Exit 1 = WARNING (refresh now).
# Usage: bash ops/check_oauth_expiry.sh

set -e
BLOB=$(security find-generic-password -s "Claude Code-credentials" -w 2>/dev/null) || {
    echo "ERROR: Could not read 'Claude Code-credentials' from Keychain. Is Claude Code installed?"
    exit 2
}
EXP_MS=$(echo "$BLOB" | jq -r .claudeAiOauth.expiresAt) || {
    echo "ERROR: Could not parse expiresAt from Keychain blob"
    exit 2
}

NOW_S=$(date +%s)
EXP_S=$((EXP_MS / 1000))
SEC_LEFT=$((EXP_S - NOW_S))
HRS_LEFT=$(awk -v s="$SEC_LEFT" 'BEGIN{printf "%.1f", s/3600}')

EXP_HUMAN=$(date -r "$EXP_S" 2>/dev/null)

if [ $SEC_LEFT -lt 7200 ]; then
    # Less than 2 hours left
    echo "WARNING: Claude Code OAuth token expires in ${HRS_LEFT}h (at $EXP_HUMAN)"
    echo "  Refresh BEFORE starting any new 2hr-capped runs."
    echo "  Refresh: open Claude Code on your Mac (any short interaction) then run:"
    echo "    bash ops/refresh_gke_oauth.sh"
    exit 1
else
    echo "OK: Claude Code OAuth token has ${HRS_LEFT}h left (expires $EXP_HUMAN)"
    exit 0
fi
