#!/usr/bin/env bash
# /run-agent.sh for cybench/mobilecybench:claudecode_<version>
# Thin bash bootstrap; all parsing + dispatch lives in Python.

set -euo pipefail

TASK=/app/task.json
EXPLOIT_DIR=/app/agent_exploit
RUN_DIR=/app/agent_run

mkdir -p "$EXPLOIT_DIR" "$RUN_DIR"
exec >>"$RUN_DIR/agent.log" 2>&1

exec python -m agent.claude_code.run_in_container "$TASK"
