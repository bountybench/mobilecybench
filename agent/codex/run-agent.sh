#!/usr/bin/env bash
# Thin bash bootstrap; parsing + dispatch live in Python.

set -euo pipefail

TASK=/app/task.json
EXPLOIT_DIR=/app/agent_exploit
RUN_DIR=/app/agent_run

mkdir -p "$EXPLOIT_DIR" "$RUN_DIR"

# Detached docker exec does not capture stdout; redirect to in-container log.
exec >>"$RUN_DIR/agent.log" 2>&1

# Codex CLI requires an API-key login. Fail fast if missing so we don't burn
# wall-clock budget on a doomed run.
if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "FATAL: OPENAI_API_KEY not set in env" >&2
  exit 2
fi
echo "$OPENAI_API_KEY" | codex login --with-api-key

exec python -m agent.codex.run_in_container "$TASK"
