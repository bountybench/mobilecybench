#!/usr/bin/env bash
# Restore wallabag victim state after pm clear by logging a victim user
# into the Android app. Defaults to victim_alice (creds in secrets.json);
# callers can override with `prepare_victim.sh <username> <password>` if a
# task needs a different victim identity.
#
# Victim must NOT be the agent identity declared in metadata.json.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

case "$#" in
    0)
        VICTIM_USER="victim_alice"
        VICTIM_PASS="$(jq -r '.victim_alice_password' "$SCRIPT_DIR/secrets.json")"
        if [ -z "$VICTIM_PASS" ] || [ "$VICTIM_PASS" = "null" ]; then
            echo "[prepare_victim] Missing victim_alice_password in secrets.json" >&2
            exit 1
        fi
        ;;
    2)
        VICTIM_USER="$1"
        VICTIM_PASS="$2"
        ;;
    *)
        echo "Usage: $(basename "$0") [<username> <password>]" >&2
        exit 1
        ;;
esac

exec bash "$SCRIPT_DIR/_login.sh" "$VICTIM_USER" "$VICTIM_PASS"
