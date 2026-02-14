# Getting Started

This guide gets a first-time user from zero to a working emulator and a basic app run.

## Quickstart (most users)

Docker should be running before you start (most apps use containers).

```bash
git clone https://github.com/bountybench/mobilecybench
cd mobilecybench
python3 -m venv .venv
source .venv/bin/activate   # Windows: .\\.venv\\Scripts\\activate
pip install -r requirements.txt
bash setup.sh --init-submodules conversations
```

Windows note: `setup.sh` and the emulator scripts require WSL or Git Bash. Use the Windows venv activation line above.

To run the AI agent, provide an API key. We currently support Google and OpenAI models and recommend using either `gemini-3-pro-preview` or `gpt-5.2`

```bash
echo OPENAI_API_KEY=sk-... > agent/.env
python runner.py conversations
```

**Important:** Do not start the emulator manually before running `runner.py` — it manages its own emulator lifecycle (start, install, cleanup) and will fail if one is already running. If you see `Running emulator(s) detected`, stop all emulators first with `./stop_emulator.sh`.

The default mode is **discovery** (find unknown vulnerabilities). To run in **exploit mode** (exploit a synthetic vulnerability), set `"workflow": "exploit"` in `runner_config.json`. See `documentation/EXPERIMENTS.md` for details on both modes.

If you do not want to use an API key, run in dry-run mode instead:

```bash
python runner.py conversations --config runner_config_dryrun.json
```

## 1) System prerequisites

- Python 3.11+ (3.12 or lower recommended for agent dependencies)
- Docker Desktop (for agent stack and some app environments)
- Java (required for Android builds; setup.sh enforces OpenJDK 17+)

## 2) Clone and create a Python environment

```bash
git clone https://github.com/bountybench/mobilecybench
cd mobilecybench
python3 -m venv .venv
source .venv/bin/activate   # Windows: .\\.venv\\Scripts\\activate
pip install -r requirements.txt
```

## 2.1) Manual checks (recommended for first-time setup)

Use these to confirm system-level dependencies before running `setup.sh`.

```bash
python3 --version
java -version
docker --version
```

## 3) Install Android SDK and emulator

```bash
bash setup.sh
```

```bash
bash setup.sh --init-submodules  # initialize all submodules (apps)
```

Notes:

- Default SDK is 35. To use a different version: `./setup.sh --sdk 34 --system-image google_apis`.
- You can also pass an app name to auto-select the SDK from its `metadata.json` (example: `./setup.sh conversations`).
- `setup.sh` installs Android SDK packages, creates the AVD, and generates `start_emulator.sh`, `stop_emulator.sh`, and `check_device.sh`.
- To initialize submodules during setup, use `--init-submodules` (all) or `--init-submodules <app_name>` (single app).
- `setup.sh` installs `apktool` if it is missing.

## 4) Obtain API key(s)

To run the agent, an API key is required in a `.env` file in the `agent/` directory. Supported model providers are listed in `agent/model_providers/factory.py`.

```bash
cd agent && touch .env
echo OPENAI_API_KEY="sk..." > .env
```

## 5) Pick an app

List available apps:

```bash
ls apps
```

Pick any existing app directory. Example: `conversations`.

## 6) Run a baseline experiment

Make sure no emulators are running (`./stop_emulator.sh`), then:

```bash
python runner.py <app_name>
```

What happens next:

- The runner starts and manages its own emulator.
- The app is built or downloaded.
- The app is installed and launched.
- The agent runs, then probes evaluate the results.
- The emulator is stopped automatically on completion.

If you only want to verify setup without running an LLM, use dry-run:

```bash
python runner.py <app_name> --config runner_config_dryrun.json
```

## 7) Submodules and Java version notes

- Apps use a git submodule at `apps/<app_name>/codebase`. Initialize/update submodules if you are working with an existing app directory:

```bash
git submodule update --init apps/<app_name>/codebase
```

- Java version for builds is app-specific (see `apps/<app_name>/metadata.json`).

## 8) Where to go next

- To add a new app: `documentation/ADDING_APPS.md`
- To run or configure the agent: `documentation/AGENT_SETUP.md`
- To generate static analysis reports: `documentation/STATIC_ANALYSIS.md`
- For troubleshooting: `documentation/TROUBLESHOOTING.md`
