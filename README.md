# MobileCybench

MobileCybench is a framework to capture agentic offensive cyber-capabilities in open source android applications. It builds or downloads apps, installs them in an emulator, runs an AI agent, and runs verifiers.

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
./start_emulator.sh
./check_device.sh
python runner.py conversations
```

Agent type defaults to `custom`; use `--agent-type codex` for Codex mode.

Windows note: `setup.sh` and emulator scripts require WSL or Git Bash.

## Documentation

- `documentation/README.md` — docs index and recommended path
- `documentation/GETTING_STARTED.md` — full setup and first run
- `documentation/EXPERIMENTS.md` — running experiments, configs, build modes
- `documentation/ADDING_APPS.md` — adding apps (includes full working example)
- `documentation/CI_VALIDATION.md` — CI modes and local CI
- `documentation/STATIC_ANALYSIS.md` — static report generation
- `documentation/SYNTHETIC_VULNERABILITIES.md` — synthetic vuln workflow
- `documentation/TROUBLESHOOTING.md` — common issues
- `documentation/AGENT_SETUP.md` — agent setup and agent types
- `agent/ARCHITECTURE.md` — agent architecture and behavior
- `documentation/COMMANDS.md` — command reference grouped by workflow
