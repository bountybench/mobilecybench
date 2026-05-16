# Bring Your Own Agent (BYO)

mobilecybench evaluates agents through one of two paths:

| `agent_mode` | What runs                                                                 |
| ------------ | ------------------------------------------------------------------------- |
| `custom`     | Built-in in-process Python loop. Stays as-is; no contract surface.        |
| `external`   | Your Docker image. The harness delivers a `task.json`, runs `/run-agent.sh`, and reads filesystem artifacts back. |

This page documents the **`external`** contract. The reference codex and claude-code images ship as `cybench/mobilecybench:codex_<v>` and `cybench/mobilecybench:claudecode_<v>`; a lab BYO image satisfies the same contract.

## The contract in one paragraph

Your image ships an executable `/run-agent.sh`. The harness creates the container with `command="sleep infinity"`, installs the test CA, delivers `/app/task.json`, then `docker exec`s `/run-agent.sh`. Your script reads the task, runs whatever agent loop you want, and writes:

- `/app/agent_run/result.json` — required; the harness reads this for `status`, `turns_taken`, etc.
- `/app/agent_run/conversation.jsonl` — one JSON object per turn; needed for the leaderboard.
- `/app/agent_run/agent.log` — captured via `exec >>$RUN_DIR/agent.log 2>&1` in the script.
- `/app/agent_exploit/exploit.sh` (RA workflow) **or** `/app/agent_exploit/exploit_apk/dist/com.mobilecybench.exploit.apk` (MA workflow) — the work-product probes score.

If wall-clock time runs out, the harness sends `SIGKILL` to the container; `result.json` may be absent (treated as `status: "timeout"`).

## Files to ship

### `Dockerfile`

```dockerfile
FROM cybench/mobilecybench-kali:<pinned-version>
# Install your agent (CLI, runtime, etc.)
RUN curl -fsSL https://your-domain/install-agent.sh | sh

COPY run-agent.sh /run-agent.sh
RUN chmod +x /run-agent.sh

# Docker's `command=` (the idle `sleep infinity` the harness sets) overrides
# CMD, not ENTRYPOINT. Explicit clear in case the base layer set one.
ENTRYPOINT []
```

Pin the kali base by digest (`FROM cybench/mobilecybench-kali@sha256:...`) if you want reproducibility.

### `/run-agent.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail

TASK=/app/task.json
EXPLOIT_DIR=/app/agent_exploit
RUN_DIR=/app/agent_run

mkdir -p "$EXPLOIT_DIR" "$RUN_DIR"

# Detached docker exec does not capture stdout; redirect to in-container log.
exec >>"$RUN_DIR/agent.log" 2>&1

# Atomic result.json: write tmpfile then rename. mv is atomic on the same fs.
write_result() { jq -n "$@" > "$RUN_DIR/result.json.tmp" && mv "$RUN_DIR/result.json.tmp" "$RUN_DIR/result.json"; }

# ... read $TASK, run your agent, write $EXPLOIT_DIR/exploit.sh ...

if mythos-cli run --task-file "$TASK" --exploit-dir "$EXPLOIT_DIR"; then
  write_result '{status:"completed", turns_taken:1}'
else
  rc=$?
  write_result --arg rc "$rc" '{status:"error", turns_taken:0, exit_code:($rc|tonumber)}'
  exit "$rc"
fi
```

No `trap` / no `setsid` / no graceful-shutdown logic. Docker doesn't propagate signals from pid 1 to exec'd children, so in-script SIGTERM grace is unreliable. Flush per-turn state atomically and assume the harness can kill you at any moment.

## `task.json` (input)

Schema: [`schemas/task.schema.json`](../schemas/task.schema.json). Notable fields:

| Field | Notes |
| --- | --- |
| `run_id` | Stable identifier (`logs/experiment_<uuid>`). Embed in any conversation events you emit. |
| `workflow` | `"exploit"` or `"redteam"`. |
| `prompt` | Fully assembled workflow prompt — relay to your CLI / API verbatim. Test credentials are embedded here when relevant. |
| `model` | Defender model id. Forward to your CLI. |
| `agent_wallclock_seconds` | Harness-side SIGKILL deadline; the harness owns it, but your agent can also use it for internal pacing. |
| `reasoning_effort` | `"low"` / `"medium"` / `"high"` / null. v1 common-denominator. |
| `no_codebase` | When true, `/app/apk/` is mounted (not `/app/codebase/`). |
| `vuln_id` | Synthetic vuln id when `workflow="exploit"` + RA mode; else null. |

## `result.json` (output)

Schema: [`schemas/result.schema.json`](../schemas/result.schema.json). Required: `status`, `turns_taken`. Status enum: `completed | timeout | error | dry_run | unknown`.

Anything else is best-effort: `cost_usd`, `model`, `final_message`, `tool_call_count`, `unique_tools`, `token_totals`, `error_traceback`. Missing optional fields get schema defaults; unknown fields pass through.

## Environment your container sees

Forwarded by the harness:

- **Auth tokens** (operator's `.env`, forwarded as-is — your CLI picks what it needs): `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`, `CLAUDE_CODE_OAUTH_REFRESH_TOKEN`. Source of truth: `agent/runtime/container.py:AUTH_ENV_PASSTHROUGH`.
- **Runtime wiring** (harness sets the values): `HTTPS_PROXY` / `HTTP_PROXY` / `NO_PROXY` (Squid sidecar), `ADB_SERVER_SOCKET=tcp:adb-proxy:5037`.

## How the reference images plug in

Both reference images use a thin bash bootstrap that delegates parsing + result emission to Python:

```bash
# agent/codex/run-agent.sh
exec python -m agent.codex.run_in_container "$TASK"
```

`agent/{codex,claude_code}/run_in_container.py` does the CLI-specific work: builds the argv, streams JSONL events through the shared `CodexEventParser` / `ClaudeCodeEventParser`, writes `conversation.jsonl`, and emits `result.json`. Use them as worked examples for your own image.

## Operator config

```json
{
  "agent_mode": "external",
  "agent_image": "your-org/your-agent:v1",
  "model": "claude-sonnet-4-6",
  "agent_wallclock_seconds": 1800
}
```

The legacy `agent_mode: "codex"` and `agent_mode: "claude-code"` values were removed. Use `agent_mode: "external"` with the reference-image tag instead. Config validation rejects the old values with the migration string.
