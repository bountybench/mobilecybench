#!/usr/bin/env bash
# Thin bash bootstrap; parsing + dispatch live in Python.

set -euo pipefail

TASK=/app/task.json
EXPLOIT_DIR=/app/agent_exploit
RUN_DIR=/app/agent_run

mkdir -p "$EXPLOIT_DIR" "$RUN_DIR"

# Detached docker exec does not capture stdout; redirect to in-container log.
exec >>"$RUN_DIR/agent.log" 2>&1

exec python -m agent.opencode.run_in_container "$TASK"
