#!/usr/bin/env bash
# /run-agent.sh for cybench/mobilecybench:codex_<version>
# Thin bash bootstrap; all parsing + dispatch lives in Python.

set -euo pipefail

TASK=/app/task.json
EXPLOIT_DIR=/app/agent_exploit
RUN_DIR=/app/agent_run

# Harness pre-creates these in setup_runtime_environment; defense-in-depth.
mkdir -p "$EXPLOIT_DIR" "$RUN_DIR"

# Detached docker exec does not capture stdout; redirect to in-container log.
exec >>"$RUN_DIR/agent.log" 2>&1

# Auth: codex CLI expects an API-key login. Harness forwards OPENAI_API_KEY
# via env. Login is idempotent; fail loudly if the key is missing so the run
# aborts before burning wall-clock budget.
if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "FATAL: OPENAI_API_KEY not set in env" >&2
  exit 2
fi
echo "$OPENAI_API_KEY" | codex login --with-api-key

exec python -m agent.codex.run_in_container "$TASK"
