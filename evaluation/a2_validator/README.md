# A2-style Task Validator

A reimplementation of the Task Validator from A2 (Wang & Zhou 2025, arXiv 2508.21579), used as an agentic baseline to compare with the MobileCyBench probes on the same exploit reports. A2's code and prompts are not public, so this is "A2-style": we reimplement the Validator's 5-step oracle procedure (Sec. 4.2) and its read-only tool set (Table 2) and write our own prompt (`prompt.md`).

## What the Validator gets

- The claim: the exploit agent's own writeup (`final_message` of its `agent_run/result.json`), as `/work/claim.md`.
- A short threat-model statement (attack setting and what the attacker legitimately owns), as `/work/threat_model.md`.
- The target app's source without `.git`, mounted read-only at `/work/source`.
- Read-only access to the device (and, for remote-attacker runs, the backend) through `mcbv`.

It never gets probe code, probe verdicts, labels, or `paper_planning/exploit_corpus/index.csv`.

## Read-only enforcement (outside the agent)

The guarantee is the same for every agent CLI because it does not depend on the agent:

- The Validator runs in a container (`image/Dockerfile`) on the Docker network `a2v_internal` (`internal: true`, no route to the host or internet). The image has no `adb` and no database clients.
- Its only way out is the `a2v-egress` Squid sidecar (`image/squid.conf`): HTTPS to the model APIs and HTTP to the gateway port on the host. Everything else, including the host adb server (5037), is denied.
- `gateway.py` runs on the host, owns adb and docker, and serves the ops below. Every request is policy-checked and appended to `gateway_audit.jsonl`.
- The runner hashes the app's state (all files under the app's data dirs, installed packages, resumed activity, and for remote-attacker runs the backend DB dump) before and after the Validator, and records whether it changed.

| A2 Validator tool (Table 2) | `mcbv` op | Notes |
|---|---|---|
| execute_shell_command | `shell "<cmd>"` | allowlisted read-only commands only (`ls cat grep find dumpsys getprop ps logcat -d settings get content query pm list/path/dump ...`); `am`, `input`, `pm` writes, `rm`, `touch`, `settings put`, `content insert`, pipes, redirects and `;` are refused |
| pull_device_file | `pull` | returns content; saved into the Validator's workdir |
| check_file_existence | `exists` | |
| analyze_file_content | `grep` | |
| list_directory_contents | `ls` | |
| (SQLite read) | `sqlite <db> "<SELECT>"` | runs on a host-side copy of the DB; SQLite authorizer allows reads only |
| capture_ui_layout | `ui-dump` | `uiautomator dump /dev/tty` (writes no file) |
| find_ui_elements, verify_element_exists | `ui-find` | |
| search_system_logs | `logcat [regex]` | |
| extract_source_code, search_code_patterns, enumerate_source_files | (none needed) | the agent's own file tools on `/work/source` |
| execute_python_script, create_local_file, read_local_file | (none needed) | the agent's own tools in `/work/scratch` |
| (remote-attacker extension) | `http-get`, `db-query` | GET to backend URL prefixes; single SELECT in a read-only DB session |

## Running

From the repo root, with no emulator running:

```
python -m evaluation.a2_validator.replay_and_validate --cell <model__vis__threat__app__aN> \
    --claim-json <run>/agent_run/result.json --exploit-dir <run>/agent_exploit \
    --source-dir <app source without .git> --out <dir>
```

This runs `runner.py` (replay of the saved exploit, then the probes) and runs the Validator from a patched `Workflow.cleanup`, i.e. on the post-probe state and before the harness tears it down. `validate.py` alone validates whatever state the device is in now.

The Validator runs only on Claude Code with the Claude subscription: `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`) is read from `mobilecybench/.env`, which is parsed, never sourced, and no other key is loaded. The Codex and Gemini code paths in `validate.py` are kept but unused; `validate()` refuses them.

Outputs per validation: `validation.json` (verdict, schema errors, wall clock, cost, tokens, state hashes and diff, gateway and proxy counts), `events.jsonl` (raw CLI stream), `gateway_audit.jsonl`, `proxy_access.log`, `work/` (inputs and the agent's scratch files). Cost is the CLI-reported `total_cost_usd` for Claude Code and is derived from token counts and `utils/token_pricing.json` for Codex and Gemini.

## Differences from A2

- A2's Validator is one role in a LangGraph Planner/Executor/Validator loop; here it runs once per report, after the fact, with no feedback to an executor.
- A2 uses Gemini 2.5 (thinkingBudget 24576, 300 s per call, at most 20 iterations); here the Validator is an agent CLI with a whole-validation wall-clock limit (default 900 s).
- A2's `execute_shell_command` is not restricted to read-only commands in Table 2; ours is, so the read-only property holds by construction.
