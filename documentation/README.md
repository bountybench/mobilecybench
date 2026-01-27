# MobileCybench Documentation

Start here if you are new to the repo. This docs set is a simple, task-oriented guide for running experiments and adding apps.

## Recommended path

1. Read `documentation/GETTING_STARTED.md` to clone, install, and start the emulator.
2. Read `documentation/EXPERIMENTS.md` to run a baseline or agent-driven experiment.
3. If you are adding an app, read `documentation/ADDING_APPS.md` and `documentation/STATIC_ANALYSIS.md`.
4. For synthetic vulnerabilities, read `documentation/SYNTHETIC_VULNERABILITIES.md`.
5. For the AI agent stack, read `documentation/AGENT_SETUP.md` or `agent/ARCHITECTURE.md` for agent behavior and architecture.
6. For CI behavior and local CI, read `documentation/CI_VALIDATION.md`.
7. If anything fails, check `documentation/TROUBLESHOOTING.md`.
8. For command reference, read `documentation/COMMANDS.md`.

## What this repo is

MobileCybench is a framework to capture agentic offensive cyber-capabilities in open source android applications. Each app lives under `apps/<app_name>/` with standardized setup scripts, metadata, probes, and vulnerability scenarios. The runner orchestrates:

- Android emulator setup
- App build and install
- Pre/post evaluation
- Optional agent execution
- Optional exploit execution and validation

## Repo map

See the repo map in `documentation/ADDING_APPS.md` (key directories).

## If you need a single entry point

Use the following commands to get a working environment and then run an app:

```bash
git clone <repo_url>
cd mobilecybench
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
bash setup.sh
./start_emulator.sh
./check_device.sh
python runner.py <app_name>
```

Replace `<app_name>` with a directory under `apps/` (for example, `conversations`).
Agent type defaults to `custom`; override with `--agent-type supervisor` or `--agent-type codex`.

## More on apps

- Every app must provide an APK via `setup_app_source.sh` or `metadata.json:download_link` (at least one is mandatory).
- Apps are git submodules under `apps/<app_name>/codebase`; initialize/update them if needed.
- Some apps require Docker even without the agent stack; check if app has `container_names` defined in `apps/<app_name>/metadata.json`.
