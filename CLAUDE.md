# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

MobileCybench is a framework for evaluating agentic offensive cyber-capabilities against open-source Android applications. It orchestrates Android emulators, AI agents (LLM-driven), Docker-based security tools (Kali containers), and structured vulnerability probes to assess how well AI agents can discover and exploit security vulnerabilities.

Two evaluation modes exist:
- **Discovery**: Agent finds unknown vulnerabilities in an app
- **Exploit**: Agent exploits known synthetic vulnerabilities injected via patches

## Prerequisites

- Python 3.11+ (3.12 or lower recommended)
- Docker Desktop running
- Java (OpenJDK 17+ enforced by setup.sh)

## Key Commands

```bash
# Initial setup
bash setup.sh --init-submodules <app_name>
./start_emulator.sh
./check_device.sh

# Run an experiment
python runner.py <app_name>                          # Discovery mode (default)
python runner.py <app_name> --config runner_config.json  # Custom config

# Build APKs
./build_apk.sh <app_name>                           # Build from source
./build_apk.sh <app_name> --vuln vuln_0             # Build with synthetic vulnerability

# Local CI validation
./run_ci_local.sh apps/<app_name>
./run_ci_local.sh apps/<app_name> --skip-build       # Skip APK build
./run_ci_local.sh apps/<app_name> --unit-tests       # Run unit tests only
./run_ci_local.sh apps/<app_name> --test-synthetic-vuln <vuln_dir>

# Testing
pytest                                               # All tests
pytest tests/workflows/                              # Specific directory
pytest -m slow                                       # Tests marked slow

# Linting (also runs as pre-commit hook)
bash run_linter.sh

# Probes
bash run_checks.sh <app_name>                        # Run all 4 CIA probes
```

## Architecture

### Execution Flow

`runner.py` is the main entry point. It creates a **Workflow** (Discovery or Exploit), then runs a 5-step pipeline: validate → setup runtime (emulator + APK + Docker backends) → setup agent → run agent → evaluate.

### Workflow System (`workflows/`)

`base.py` defines an abstract Workflow. `discovery.py` runs a CustomAgent to find vulnerabilities, then evaluates with probes. `exploit.py` applies a vulnerability patch, mounts verify/exploit files, and checks if the agent successfully exploits the synthetic vulnerability.

### Agent System (`agent/`)

`custom_agent.py` is the main LLM-driven agent. It builds a system prompt from templates, maintains message history, and executes tools via a **ToolRuntime** running in a Kali Docker container. Model providers (`agent/model_providers/`) use a factory pattern that auto-selects based on model name (OpenAI, Google, Claude via LiteLLM).

Tools available to the agent are registered in `agent/tools/runtime.py` with Pydantic schema validation: `execute_command`, `get_current_ui_state`, `execute_command_with_ui_state`.

### App Structure (`apps/<app_name>/`)

Each app is standardized with:
- `codebase/` — git submodule from cy-suite GitHub org
- `metadata.json` — required config (gh_link, commit_version, sdk, java, package_name, app_server, container_names)
- `build.sh` / `start_runtime.sh` / `cleanup.sh` — lifecycle scripts
- `test_confidentiality.py`, `test_integrity.py`, `test_availability.py`, `test_access_control.py` — CIA probes
- `docker-compose.yml` — optional app-specific backend services
- `synthetic_vulnerabilities/vuln_N/` — vulnerability.patch, verify_files/, exploit_files/
- `static_vuln_reports/` — pre-generated Semgrep/MobSFScan/QARK reports

### Docker Infrastructure

Apps can define backend containers (databases, servers) via `docker-compose.yml` on a shared `shared_net` network. The agent runs inside a Kali container (`agent/kali/`) with mounted codebase and ADB access. The orchestrator (`orchestrator/`) manages container lifecycle.

### Tracking and Observability (`utils/`)

- `time_tracker.py` — per-LLM-call timing with p50/p95/p99 stats
- `token_tracker.py` — token usage, cost calculation (via `token_costs.py` + `token_pricing.json`), JSONL logging
- `logger.py` — centralized logging with LoggerManager, session-based log files

## Configuration

`runner_config.json` controls experiment behavior: workflow type, build mode (`source`/`download-apk`/`skip-apk`), ADB access level, model selection, token/context limits, and allowed tools. See `models/config.py` for the full `RunnerConfig` Pydantic model.

## CI

CI runs on PRs (`.github/workflows/ci.yml`). It detects changed apps and runs two modes:
- **Simple CI**: build + install APK on emulator
- **Full CI**: probes + vulnerability scenario validation (requires probe scripts to exist)

Metadata schema validation checks: gh_link, commit_version, sdk, java, package_name, app_server, container_names.

## Linting

Configured in `pyproject.toml` under `[tool.ruff]`: rules E, F, I are enabled; E501 (line length) is ignored.

## Test Markers

Defined in `pyproject.toml`: `pricing`, `token_tracker`, `time_tracker`, `slow`.
