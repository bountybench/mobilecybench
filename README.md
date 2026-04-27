# MobileCybench

MobileCybench is a framework to capture agentic offensive cyber-capabilities in open source android applications. Each app lives under `apps/<app_name>/` with standardized setup scripts, metadata, probes, and vulnerability scenarios. The runner orchestrates:

## Table of Contents

1. [Quick Start](#quick-start)
2. [Prerequisites](#prerequisites)
3. [Documentation](#documentation)

## Prerequisites

- Python 3.11+ (3.12 or lower recommended for agent dependencies)
- Docker Desktop running
- Java (required for Android builds; setup.sh enforces OpenJDK 17+)

## Quick Start

Docker should be running before you start (most apps use containers).

```bash
git clone https://github.com/bountybench/mobilecybench
cd mobilecybench
python3 -m venv .venv
source .venv/bin/activate   # Windows: .\.venv\Scripts\activate
pip install -r requirements.txt
bash setup.sh --init-submodules conversations
# Set the API key for whichever provider you plan to use (see the model section below). For example, to use the default gpt-5.5:
echo OPENAI_API_KEY=sk-... > agent/.env
python runner.py conversations
```

**Supported model providers** (see `agent/model_providers/factory.py:SupportedModel` for the current list and [Adding a New Model](documentation/ADDING_MODELS.md) to register your own):

| Provider | Env var | Example models |
|---|---|---|
| OpenAI (Responses API) | `OPENAI_API_KEY` | `gpt-5.5`, `gpt-5.4`, `gpt-5.2` (+ `-pro`, `-codex` variants) |
| Anthropic (via LiteLLM) | `ANTHROPIC_API_KEY` | `claude-opus-4-7`, `claude-sonnet-4-6`, `claude-opus-4-6` |
| Google (via LiteLLM) | `GEMINI_API_KEY` | `gemini-3.1-pro`, `gemini-3-pro-preview` |

Pick the model in `runner_config.json:model` (default: `gpt-5.5`).

A run is defined by three independent axes:

- **Workflow** (`workflow`) — `exploit` (default) tells the agent what to exploit and scores a single verifier run; `redteam` withholds the bug and scores via two-phase patch-differential replay.
- **Task type** — *synthetic* (a bug we introduce in an app) or *zero-day* (a bug that existed in the wild). Selected by `synthetic_vuln_id` or `task` respectively. `exploit` accepts only synthetic; `redteam` accepts either.
- **Attacker model** — `malicious_app` (agent builds an exploit APK) or `remote_attacker` (agent writes `exploit.sh`). Declared per-task in the task bundle's `metadata.json`.

The committed `runner_config.json` defaults to `workflow: "exploit"`, `synthetic_vuln_id: "vuln_0"`. See [Experiments](documentation/EXPERIMENTS.md) for the full walkthrough and [Red Team Workflow](documentation/REDTEAM.md) for redteam scoring.

To verify your environment without using tokens, set `"dry_run": true` in `runner_config.json` to launch an interactive Kali shell instead of the agent.

**Important:** Do not start the emulator manually before running `runner.py` — it manages its own emulator lifecycle and will fail if one is already running. If you see `Running emulator(s) detected`, stop all emulators first with `./stop_emulator.sh`.

The emulator helper scripts (`start_emulator.sh`, `check_device.sh`) are for manual debugging and dry-run mode only.

Windows note: `setup.sh` and emulator scripts require WSL or Git Bash.

## Documentation

- [Getting Started](documentation/GETTING_STARTED.md) — full setup and first run
- [Experiments](documentation/EXPERIMENTS.md) — running experiments, configs, build modes
- [Adding Apps](documentation/ADDING_APPS.md) — adding apps (includes full working example)
- [CI Validation](documentation/CI_VALIDATION.md) — CI modes and local CI
- [Synthetic Vulnerabilities](documentation/SYNTHETIC_VULNERABILITIES.md) — synthetic vuln workflow
- [HTTPS Upgrade Guide](documentation/HTTPS_UPGRADE_GUIDE.md) — upgrading apps from HTTP to HTTPS
- [Troubleshooting](documentation/TROUBLESHOOTING.md) — common issues
- [Architecture](documentation/ARCHITECTURE.md) — system architecture and agent environment
- [Commands](documentation/COMMANDS.md) — command reference grouped by workflow
- [GKE Infrastructure](infra/gke/README.md) — running experiments at scale on Google Kubernetes Engine (GKE)
