# Agent Setup

This guide covers the AI agent runtime, model providers, and how to run agent modes.

## Prerequisites

- Docker Desktop running
- Python 3.11+ (3.12 or lower recommended)
- Android emulator setup via `setup.sh`
- API key for the model provider (OpenAI/Gemini) or Codex CLI key if using the Codex agent type

Architecture reference: `agent/ARCHITECTURE.md`

## 1) Python environment

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .\\.venv\\Scripts\\activate
pip install --upgrade pip
pip install -r requirements.txt
```

## 2) API keys and providers

The agent reads API keys from `agent/.env` (one `KEY=VALUE` per line). Supported model providers are determined by `agent/model_providers/factory.py`:

- OpenAI (`OPENAI_API_KEY`)
- Gemini (`GEMINI_API_KEY`)

Create `agent/.env` with the key you plan to use:

```bash
echo "OPENAI_API_KEY=your_api_key_here" > agent/.env
```

For Gemini:

```bash
echo "GEMINI_API_KEY=your_api_key_here" > agent/.env
```

Codex CLI agent type uses `CODEX_API_KEY` (see `agent/codex`):

```bash
echo "CODEX_API_KEY=your_api_key_here" >> agent/.env
```

## 3) Start the agent runtime

The runner starts the agent environment (Kali container) automatically. Ensure Docker is running before you start:

```bash
python runner.py <app_name>
```

Agent type defaults to `custom`; override with `--agent-type supervisor`or `--agent-type codex`.

## 4) Run in dry-run mode

Dry-run mode sets up the full environment without calling any model APIs.

```bash
python runner.py <app_name> runner_config_dryrun.json
```

You will get an interactive shell in the Kali container.
Agent type defaults to `custom`; override with `--agent-type supervisor` or `--agent-type codex`.

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
python runner.py <app_name> --agent-type custom        # default
python runner.py <app_name> --agent-type supervisor    # hierarchical agent
python runner.py <app_name> --agent--type codex        # codex
```

## 7) Supervisor mode checklist

Supervisor mode requires pre-generated static reports for the app:

1. Generate reports (Semgrep required, MobSFScan/QARK optional): `documentation/STATIC_ANALYSIS.md`
2. Confirm reports exist under `apps/<app_name>/static_vuln_reports/`
3. Run the supervisor agent:

```bash
python runner.py <app_name> --agent-type supervisor
```

If reports are missing, the static-analysis worker will have no findings to prioritize.
