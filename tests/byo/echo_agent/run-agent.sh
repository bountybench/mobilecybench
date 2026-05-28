#!/usr/bin/env bash
# Echo agent: reference BYO-contract stub.
# Reads /app/task.json, writes a known exploit.sh + conversation.jsonl +
# result.json. No LLM, no tools, no work. Used to exercise the contract.

set -euo pipefail

TASK=/app/task.json
EXPLOIT_DIR=/app/agent_exploit
RUN_DIR=/app/agent_run

mkdir -p "$EXPLOIT_DIR" "$RUN_DIR"

# Detached docker exec does not capture stdout; redirect to in-container log.
exec >>"$RUN_DIR/agent.log" 2>&1

write_result() {
  jq -n "$@" > "$RUN_DIR/result.json.tmp" \
    && mv "$RUN_DIR/result.json.tmp" "$RUN_DIR/result.json"
}

# Echo selected task fields into a known exploit.sh.
APP_NAME=$(jq -r '.app_name' "$TASK")
VULN_ID=$(jq -r '.vuln_id // "none"' "$TASK")

cat > "$EXPLOIT_DIR/exploit.sh" <<EOF
#!/usr/bin/env bash
# echo-agent stub for app=$APP_NAME vuln=$VULN_ID
exit 0
EOF
chmod +x "$EXPLOIT_DIR/exploit.sh"

# One synthetic turn into conversation.jsonl.
jq -nc --arg ts "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" '{
  run_id: "echo-agent",
  turn_number: 1,
  timestamp: $ts,
  role: "assistant",
  response_id: null,
  assistant_text: "echo-agent done",
  reasoning_summary: null,
  tool_calls: [],
  observations: [],
  status: "ok"
}' > "$RUN_DIR/conversation.jsonl"

write_result \
  --arg msg "echo-agent finished" \
  '{status:"completed", turns_taken:1, final_message:$msg, cost_usd:0}'
