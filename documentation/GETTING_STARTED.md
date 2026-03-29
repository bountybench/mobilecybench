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

The default mode is **discovery** (find unknown vulnerabilities). Other modes: **exploit** (exploit a known synthetic vulnerability) and **detection** (find vulnerabilities autonomously, evaluated via patch-differential replay). Set `"workflow"` in `runner_config.json`. See `documentation/EXPERIMENTS.md` for details.

If you do not want to use an API key, run in dry-run mode instead:

```bash
python runner.py conversations  # set "dry_run": true in runner_config.json
```

## 1) System prerequisites

- Python 3.11+ (3.12 or lower recommended for agent dependencies)
- Docker Desktop (for agent stack and some app environments)
- Java (required for Android builds; setup.sh enforces OpenJDK 17+. Please note that some apps require Java 21 to build.)

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

### Claude Code agent mode

To use the Claude Code agent (`"agent_mode": "claude-code"` in your runner config), you need OAuth tokens from a Claude Max or Pro subscription instead of an API key.

**Step 1: Install and authenticate Claude Code**

```bash
npm install -g @anthropic-ai/claude-code
claude auth login   # follow the browser flow — stores credentials in macOS Keychain
```

**Step 2: Extract tokens into `agent/.env`**

After logging in, extract your OAuth tokens from the macOS Keychain into the env file:

```bash
CREDS=$(security find-generic-password -s "Claude Code-credentials" -w)
echo "$CREDS" | python3 -c "
import json, sys
c = json.load(sys.stdin)['claudeAiOauth']
print(f'CLAUDE_CODE_OAUTH_TOKEN={c[\"accessToken\"]}')
print(f'CLAUDE_CODE_OAUTH_REFRESH_TOKEN={c[\"refreshToken\"]}')
" >> agent/.env
```

Tokens expire periodically — re-run the extraction before each session.

**Step 3: Configure `runner_config.json`**

```json
{
  "agent_mode": "claude-code",
  "agent_image": "cybench/mobilecybench:claudecode",
  "agent_timeout": 1800
}
```

The Docker image is pulled automatically. `agent_timeout` controls how long (in seconds) the CLI is allowed to run (default: 1800).

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
python runner.py <app_name>  # set "dry_run": true in runner_config.json
```

## 7) Submodules and Java version notes

- Apps use a git submodule at `apps/<app_name>/codebase`. Initialize/update submodules if you are working with an existing app directory:

```bash
git submodule update --init apps/<app_name>/codebase
```

- Java version for builds is app-specific (see `apps/<app_name>/metadata.json`).

## 8) Where to go next

- To add a new app: `documentation/ADDING_APPS.md`
- To run experiments: `documentation/EXPERIMENTS.md`
- For troubleshooting: `documentation/TROUBLESHOOTING.md`
