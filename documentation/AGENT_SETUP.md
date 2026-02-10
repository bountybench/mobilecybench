# Agent Setup

This guide covers the AI agent runtime, model providers, and how to run agent modes.

## Prerequisites

- Docker Desktop running
- Python 3.11+ (3.12 or lower recommended)
- Android emulator setup via `setup.sh`
- API key for the model provider (OpenAI/Gemini) or Codex CLI key if using the Codex agent type

Architecture reference: `agent/ARCHITECTURE.md`

## 1) Python environment
Use the setup from `documentation/GETTING_STARTED.md` (single source of truth).

## 2) API keys and providers
Copy the example file and fill in the providers you plan to use:
```bash
cp agent/.env.example agent/.env
```
Supported model providers are listed in `agent/model_providers/factory.py`.

Codex is available but not the default path; see `agent/codex` if you intend to use it. TODO: refactor `codex_agent` to share provider config.

## 3) Start the agent runtime

The runner starts the agent environment (Kali container) automatically. Ensure Docker is running before you start:

```bash
python runner.py <app_name>
```

Agent type defaults to `custom`; use `--agent-type codex` for Codex mode.

## 4) Run in dry-run mode

Dry-run mode sets up the full environment without calling any model APIs.

```bash
python runner.py <app_name> runner_config_dryrun.json
```

You will get an interactive shell in the Kali container.
Agent type defaults to `custom`; use `--agent-type codex` for Codex mode.

## 5) Run the full agent pipeline

```bash
python runner.py <app_name>
```

This will:

- Build/install the app
- Run pre-agent probes
- Run the agent
- Run post-agent probes
- Execute any agent-generated exploit script if present

## 6) Agent type selection

Use `--agent-type` to select an agent implementation:

```bash
python runner.py <app_name> --agent-type custom  # default
python runner.py <app_name> --agent-type codex  # Codex mode
```
