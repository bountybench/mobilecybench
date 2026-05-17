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

Schema: [`schemas/result.schema.json`](../schemas/result.schema.json). Status enum: `completed | timeout | error | dry_run | unknown`.

**Required:** `status`. That's it. Every other field is optional with a documented runner-side fallback (`turns_taken` defaults to row count in `conversation.jsonl`; `model` falls back to `task.model`; etc.).

**Optional fields the harness reads:** `cost_usd`, `model`, `final_message`, `exit_code`, `tool_call_count`, `unique_tools`, `token_totals` (open object — see below), `session_id`, `stop_reason`, `timing` (`{wall_ms, api_ms, ttft_ms}`), `error_traceback`. Unknown fields pass through.

### Cost reporting

If your CLI knows the cost in USD, emit it at the top level as `cost_usd` (NOT nested in `token_totals`). The harness will trust whatever you write — including a legitimate `0` for a $0 run.

**If you do not have a cost number, OMIT the key entirely.** Do not write `0` as a placeholder. The harness derives cost from `token_totals` × [`utils/token_pricing.json`](../utils/token_pricing.json) when `cost_usd` is absent, and stamps `cost_source` ∈ `{"agent", "derived", "derived_unpriced"}` so drift is auditable.

**No `token_totals` ⇒ no cost.** Derived cost is `tokens × pricing`; if the agent omits both `cost_usd` and `token_totals`, the run reports `cost_usd: 0` with `cost_source: "derived"`. Emit at least `input_tokens` / `output_tokens` if you want any cost signal.

#### Timeout / SIGKILL: emit usage per-turn, not just at end

The harness enforces `agent_wallclock_seconds` by sending SIGTERM (then SIGKILL) to your CLI. **If your agent emits token usage only in a terminal event (end-of-run), all token data is lost on every timed-out run** — both `token_totals` and any derived cost will be empty/zero. Two strategies:

- **Aggregate per turn / per call as you go.** Survives SIGTERM cleanly. The codex parser (`agent/codex/event_parser.py`) does this from `turn.completed.usage`, but codex itself only emits `turn.completed` at end-of-loop — so codex runs that don't finish within wallclock currently report `token_totals: {}`. This is a known limitation of codex's event stream, not a harness bug.
- **Emit per-turn usage events.** The claude-code parser (`agent/claude_code/event_parser.py`) accumulates from claude's `stream_event/message_delta`, gated on the CLI flag `--include-partial-messages`. Even on SIGTERM, all turns whose `message_delta` already landed are preserved.

If you're building a new BYO CLI, prefer a streaming usage emission model. Otherwise, document the gap and accept that timeout-cost is uninstructive for your agent.

### `token_totals` sub-fields

Open object. Sub-fields the harness understands for cache-aware cost derivation:

| Sub-field                   | When to emit                                                   |
| --------------------------- | -------------------------------------------------------------- |
| `input_tokens`              | Always, even when 0.                                           |
| `output_tokens`             | Always.                                                        |
| `reasoning_tokens`          | When your CLI separates reasoning from output.                 |
| `cached_input_tokens`       | When your CLI reports cache **reads**.                         |
| `cache_creation_tokens`     | When your CLI reports total cache **writes** (no TTL split).   |
| `cache_creation_tokens_5m`  | When you have a TTL split for cache writes (Anthropic).        |
| `cache_creation_tokens_1h`  | Same.                                                          |

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

`agent/{codex,claude_code}/run_in_container.py` does the CLI-specific work: builds the argv, streams events through a `BaseEventParser` subclass (`CodexEventParser` / `ClaudeCodeEventParser`), and lets the shared runner write `conversation.jsonl` + `result.json`.

The parser layer in `agent/in_container/event_parser.py` owns line buffering, turn flushing, conversation-row formatting, and result-summary shaping. To add a third BYO CLI you write a single subclass overriding `_handle_event` (a switch on your CLI's event types) — typically ~100 LOC. Use codex + claude-code as worked examples.

**Live-tailing logs.** The runner writes incrementally — every turn appends one line to `conversation.jsonl` and snapshots `result.json` (`status="unknown"` during the run, finalized at clean exit). On a wall-clock SIGKILL, the per-turn writes survive. Note: these files are inside the container, not on the host. To watch live during a run:

```bash
docker exec kali-container tail -f /app/agent_run/conversation.jsonl
```

The harness pulls them to the host's `logs/experiment_<uuid>/agent_run/` when the container exits.

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
