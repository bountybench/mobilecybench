# Bring Your Own Agent (BYO)

mobilecybench evaluates agents through one of two paths:

| `agent_mode` | What runs                                                                 |
| ------------ | ------------------------------------------------------------------------- |
| `custom`     | Built-in in-process Python loop. Stays as-is; no contract surface.        |
| `external`   | Your Docker image. The harness delivers a `task.json`, runs `/run-agent.sh`, and reads filesystem artifacts back. |

This page documents the **`external`** contract. The reference codex and claude-code images ship as `cybench/mobilecybench:codex_0.130.0-r2` and `cybench/mobilecybench:claudecode_2.1.140-r2` (the `<cli-version>-r<revision>` tag pattern lets the harness bump independently of the CLI); a lab BYO image satisfies the same contract.

## The contract in one paragraph

Your image ships an executable `/run-agent.sh`. Before invoking your agent, `agent/runtime/container.py:setup_agent_environment` creates the container (with `command="sleep infinity"`), installs the test CA, and mounts `/app/codebase` (or `/app/apk` when `no_codebase=true`). The harness (`harness/byo_agent.py`) then delivers `/app/task.json` and `docker exec`s `/run-agent.sh`. Your script reads the task, runs whatever agent loop you want, and writes:

- `/app/agent_run/result.json` — required; the harness reads this for `status`, `turns_taken`, etc.
- `/app/agent_run/conversation.jsonl` — one JSON object per turn. Required keys + types: [`schemas/conversation_turn.schema.json`](../schemas/conversation_turn.schema.json). Rows are validated; reference `BaseEventParser` subclasses emit conformant rows automatically.
- `/app/agent_run/agent.log` — captured via `exec >>$RUN_DIR/agent.log 2>&1` in the script.
- `/app/agent_exploit/exploit.sh` (RA workflow) **or** `/app/agent_exploit/exploit_apk/dist/com.mobilecybench.exploit.apk` (MA workflow) — the work-product probes score.

**Wall-clock termination.** When `agent_wallclock_seconds` elapses, the harness sends `pkill -TERM` targeting an in-container Python runner (matches `agent\..*\.run_in_container`), waits 10s for graceful flush, then `SIGKILL`s the container. If your image is the reference shape (Python runner under `agent/in_container/runner.py`), SIGTERM hits the runner and its handler writes `result.json` with `status: "timeout"` plus the per-turn state already on disk. If your image is a plain bash bootstrap, the bash script does NOT receive SIGTERM — only the in-container Python catches it. Plan accordingly: either run the reference Python runner, or flush per-turn atomically and treat SIGKILL as unrecoverable.

## Files to ship

### `Dockerfile`

```dockerfile
FROM cybench/mobilecybench-kali:v0.1.0
# Install your agent (CLI, runtime, etc.)
RUN curl -fsSL https://your-domain/install-agent.sh | sh

COPY run-agent.sh /run-agent.sh
RUN chmod +x /run-agent.sh

# Docker's `command=` (the idle `sleep infinity` the harness sets) overrides
# CMD, not ENTRYPOINT. Explicit clear in case the base layer set one.
ENTRYPOINT []
```

Pin the kali base by digest (`FROM cybench/mobilecybench-kali@sha256:...`) if you want reproducibility.

**Two image constraints the contract relies on:**

1. **Empty `ENTRYPOINT`.** The harness invokes `/run-agent.sh` (and the exploit replay container invokes `bash exploit.sh`) directly. A non-empty `ENTRYPOINT` would hijack both.
2. **Replay tooling.** Your `agent_image` is also used by the host as the **exploit replay image** — after the agent writes `exploit.sh`, the harness re-runs that script in a fresh container of the same image (`utils/run_exploit_container.sh`). The kali base bundles bash, curl, jq, adb, gradle/JDK; if you switch bases, keep these or replay will crash.

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

if your-agent-cli run --task-file "$TASK" --exploit-dir "$EXPLOIT_DIR"; then
  write_result '{status:"completed", turns_taken:1}'
else
  rc=$?
  write_result --arg rc "$rc" '{status:"error", turns_taken:0, exit_code:($rc|tonumber)}'
  exit "$rc"
fi
```

No `trap` / no `setsid` / no graceful-shutdown logic in this example. The harness's wall-clock SIGTERM targets the in-container Python runner by argv pattern, so a plain bash script like this one never receives it. Flush per-turn state atomically and treat the eventual SIGKILL as unrecoverable. (If you want graceful shutdown, run the reference Python runner — see "How the reference images plug in" below.)

## Filesystem layout inside the container

| Path | Direction | Notes |
| --- | --- | --- |
| `/app/task.json` | in | Task contract (see below). Read-only. |
| `/app/codebase/` | in | App source. Mounted when `no_codebase=false`. |
| `/app/apk/` | in | Single APK file. Mounted when `no_codebase=true` (replaces `/app/codebase`). |
| `/app/agent_run/` | out | `result.json`, `conversation.jsonl`, `agent.log`. Pulled to host after run. |
| `/app/agent_exploit/` | out | `exploit.sh` (RA) or `exploit_apk/.../*.apk` (MA). Pulled to host after run. |
| `/app/agent_output/` | out | Read-write scratch dir for synthetic-vuln mode (verify scripts read it). Pulled to host. |

## `task.json` (input)

Schema: [`schemas/task.schema.json`](../schemas/task.schema.json) — authoritative; this table is a tour. Required keys per schema: `run_id`, `app_name`, `workflow`, `package_name`, `app_server`, `emulator_server`, `apk_relpath`, `no_codebase`, `model`, `prompt`, `agent_wallclock_seconds`. Optional: `vuln_id`, `attacker_model`, `reasoning_effort`, `screenshot_mode` (in practice the harness always emits these too).

| Field | Notes |
| --- | --- |
| `run_id` | Bare uuid (e.g. `03e2c121-cb4d-481e-b668-da0dee5d84cf`). Embed in conversation events. |
| `app_name` | Directory name under `apps/` (e.g. `wallabag`). Useful for logging / artifact naming. |
| `workflow` | `"exploit"` or `"redteam"`. |
| `prompt` | Fully assembled workflow prompt — relay to your CLI / API verbatim. Test credentials and any `additional_system_prompt` from operator config are pre-merged into this string by the harness. |
| `model` | Model id. Forward to your CLI. |
| `agent_wallclock_seconds` | Harness-side SIGKILL deadline (see "Wall-clock termination" above); the agent can also use it for internal pacing. |
| `reasoning_effort` | `"low"` / `"medium"` / `"high"` / null. Forwarded to providers that accept it; ignored otherwise. |
| `no_codebase` | When true, `/app/apk/` is mounted (not `/app/codebase/`). |
| `apk_relpath` | Path to the built target APK, relative to `/app/codebase` (or `/app/apk` when `no_codebase=true`). |
| `vuln_id` | Synthetic vuln id when `synthetic_vuln_id` is set on the operator config (either `workflow="exploit"` or `workflow="redteam"` with synthetic mode). Null for zero-day redteam. |
| `attacker_model` | `"malicious_app"` / `"remote_attacker"` for redteam; `""` for exploit. |
| `screenshot_mode` | When true, capture per-turn screenshots under `agent_run/screenshots/`. |
| `app_server`, `emulator_server`, `package_name` | Live runtime endpoints + target package the harness pre-wires. Forward into your CLI's context. |

## `result.json` (output)

Schema: [`schemas/result.schema.json`](../schemas/result.schema.json). Status enum: `completed | timeout | error | dry_run | unknown`.

**Required:** `status`. That's it. Every other field is optional. The harness coerces missing typed fields to safe defaults in `utils/run_artifacts.py:normalize_agent_result` (`turns_taken=0`, `model=""`, `final_message=""`, `tool_call_count=0`, `unique_tools=[]`, `token_totals={}`, `exit_code=0`, `error_traceback=""`); unknown fields pass through.

**Optional fields the harness reads:** `cost_usd`, `model`, `final_message`, `exit_code`, `tool_call_count`, `unique_tools`, `token_totals` (open object — see below), `session_id`, `stop_reason`, `timing` (`{wall_ms, api_ms, ttft_ms}`), `error_traceback`.

### Cost reporting

If your CLI knows the cost in USD, emit it at the top level as `cost_usd` (NOT nested in `token_totals`). The harness will trust whatever you write — including a legitimate `0` for a $0 run.

**If you do not have a cost number, OMIT the key entirely.** Do not write `0` as a placeholder. The harness derives cost from `token_totals` × [`utils/token_pricing.json`](../utils/token_pricing.json) when `cost_usd` is absent, and stamps `cost_source` ∈ `{"agent", "derived", "derived_unpriced"}` so drift is auditable.

**No `token_totals` ⇒ no cost.** Derived cost is `tokens × pricing`; if the agent omits both `cost_usd` and `token_totals`, the run reports `cost_usd: 0` with `cost_source: "derived"` (or `"derived_unpriced"` when the model has no row in `token_pricing.json`). Emit at least `input_tokens` / `output_tokens` if you want any cost signal.

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

The parser layer in `agent/in_container/event_parser.py` (`BaseEventParser`) owns line buffering, turn flushing, conversation-row formatting, result-summary shaping, and per-turn token accumulation. To add a third BYO CLI you write a single subclass overriding `_handle_event` (a switch on your CLI's event types). See `agent/codex/event_parser.py` and `agent/claude_code/event_parser.py` for worked examples.

**Live-tailing logs.** The reference runner writes incrementally — every turn appends one line to `conversation.jsonl` and snapshots `result.json` (`status="unknown"` during the run, finalized at clean exit). On a wall-clock SIGKILL, the per-turn writes survive.

**These files live inside the container until the container exits.** The harness pulls `agent_run/`, `agent_exploit/`, and `agent_output/` to the host's `logs/experiment_<uuid>/` only in its `finally` block (`harness/byo_agent._pull_artifacts`). For real-time visibility during a run, exec into the container:

```bash
docker exec kali-container tail -f /app/agent_run/conversation.jsonl
```

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
