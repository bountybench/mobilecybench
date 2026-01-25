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
./start_emulator.sh
./check_device.sh
```

Windows note: `setup.sh` and the emulator scripts require WSL or Git Bash. Use the Windows venv activation line above.

If you want to run the AI agent, provide an API key. Supported model providers are listed in `agent/model_providers/factory.py`. Agent type defaults to `custom`; override with `--agent-type supervisor` or `--agent-type codex`.

```bash
echo OPENAI_API_KEY=sk-... > agent/.env
python runner.py conversations
```

If you do not want to use an API key, run in dry-run mode instead:

```bash
python runner.py conversations runner_config_dryrun.json
```

## 1) System prerequisites

- Python 3.11+ (3.12 or lower recommended for agent dependencies)
- Docker Desktop (for agent stack and some app environments)
- Android SDK and emulator (installed by `setup.sh`)
- Java 17+ (Android SDK requirement; app builds may require newer)
- Git (for submodules)
- jq (used by CI/setup scripts)
- 8GB+ RAM and 16GB+ free disk (20GB+ recommended for comfort)

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
git --version
jq --version
docker --version
```

If `jq` is missing:

- macOS: `brew install jq`
- Debian/Ubuntu: `sudo apt-get install jq`

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

## 4) Start and verify the emulator

```bash
./start_emulator.sh
./check_device.sh
```

You should see a connected emulator with the expected SDK version.

## 5) Obtain API key(s)

To run the agent, an API key is required in a `.env` file in the `agent/` directory. Supported model providers are listed in `agent/model_providers/factory.py`.

```bash
cd agent && touch .env
echo OPENAI_API_KEY="sk..." > .env
```

## 6) Pick an app

List available apps:

```bash
ls apps
```

Pick any existing app directory. Example: `conversations`.

## 7) Run a baseline experiment

```bash
python runner.py <app_name>
```

What happens next:

- The app is built or downloaded.
- The emulator is prepared.
- The app is installed and launched.
- Probes are run before and after testing.

Agent type defaults to `custom`; override with `--agent-type supervisor` or `--agent-type codex`.

If you only want to verify setup without running an LLM, use dry-run:

```bash
python runner.py <app_name> runner_config_dryrun.json
```

## 8) Required app files (minimal rule)

Every app must provide an APK by either:

- `apps/<app_name>/setup_app_source.sh` (preferred), or
- `apps/<app_name>/metadata.json` with `download_link`

At least one of these is mandatory.

## 9) Submodules and Java version notes

- Apps use a git submodule at `apps/<app_name>/codebase`. Initialize/update submodules if you are working with an existing app directory:

```bash
git submodule update --init apps/<app_name>/codebase
```

- Java version for builds is app-specific (see `apps/<app_name>/metadata.json`).

## 10) Where to go next

- To add a new app: `documentation/ADDING_APPS.md`
- To run or configure the agent: `documentation/AGENT_SETUP.md`
- To generate static analysis reports: `documentation/STATIC_ANALYSIS.md`
- For troubleshooting: `documentation/TROUBLESHOOTING.md`
