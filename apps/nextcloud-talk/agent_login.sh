#!/usr/bin/env bash
# Pre-agent login: log the agent's user into Nextcloud Talk.
#
# prepare_victim.sh is already user-parameterized (takes $1 as the user
# whose <USER>_PASSWORD is read from .env), and unlike owncloud has no
# baseline-capture stage that would conflict with seeding agent state.
# So we just dispatch to it with the agent username from metadata.json
# (single source of truth — same field the agent's prompt reads).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

AGENT_USER="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["username"])' "$SCRIPT_DIR/metadata.json")"

exec "$SCRIPT_DIR/prepare_victim.sh" "$AGENT_USER"
