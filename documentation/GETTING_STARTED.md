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

To run the AI agent, provide an API key. The built-in models cover three
providers (see `agent/model_providers/factory.py:SupportedModel` for the full
list, including older entries kept for backwards compatibility):

- **OpenAI** (Responses API) — `gpt-5.5`, `gpt-5.5-pro`;
  `gpt-5.4`, `gpt-5.4-pro`, `gpt-5.2`, `gpt-5.2-pro`, `gpt-5.2-codex`.
  Requires `OPENAI_API_KEY`.
- **Anthropic** (via LiteLLM) — `claude-opus-4-7`, `claude-sonnet-4-6`;
  `claude-opus-4-6`, `claude-sonnet-4-5-20250929`. Requires
  `ANTHROPIC_API_KEY`.
- **Google** (via LiteLLM) — `gemini-3.1-pro`; `gemini-3-pro-preview`.
  Requires `GEMINI_API_KEY`.

To add a new model, append an entry to `SupportedModel` and a pricing
row to `utils/token_pricing.json` — see
[Adding a New Model](ADDING_MODELS.md). For one-off model-sweep
exploration where cost telemetry doesn't matter, set
`"allow_unregistered_models": true` in `runner_config.json` to bypass
the registry.

```bash
echo OPENAI_API_KEY=sk-... > agent/.env
python runner.py conversations
```

**Important:** Do not start the emulator manually before running `runner.py` — it manages its own emulator lifecycle (start, install, cleanup) and will fail if one is already running. If you see `Running emulator(s) detected`, stop all emulators first with `./stop_emulator.sh`.

The default mode is **discovery** (find unknown vulnerabilities). Other modes: **exploit** (exploit a known synthetic vulnerability) and **detection** (find vulnerabilities autonomously, evaluated via patch-differential replay). Set `"workflow"` in `runner_config.json`. See `documentation/EXPERIMENTS.md` for details.

If you do not want to use an API key, run in dry-run mode instead:

```bash
python runner.py conversations --config runner_config_dryrun.json
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
claude auth login   # follow the browser flow; credentials are stored in
                    # the OS-native secret store (macOS Keychain / Linux
                    # `~/.claude/.credentials.json` / Windows Credential Manager)
```

**Step 2: Extract tokens into `agent/.env`**

After logging in, extract your OAuth tokens into `agent/.env`. Pick the
snippet for your platform.

**macOS** (Keychain):

```bash
CREDS=$(security find-generic-password -s "Claude Code-credentials" -w)
echo "$CREDS" | python3 -c "
import json, sys
c = json.load(sys.stdin)['claudeAiOauth']
print(f'CLAUDE_CODE_OAUTH_TOKEN={c[\"accessToken\"]}')
print(f'CLAUDE_CODE_OAUTH_REFRESH_TOKEN={c[\"refreshToken\"]}')
" >> agent/.env
```

**Linux** (credentials file under `~/.claude/`):

```bash
python3 -c "
import json, pathlib, sys
path = pathlib.Path.home() / '.claude' / '.credentials.json'
if not path.exists():
    sys.exit(f'Credentials file not found at {path}; run \"claude auth login\" first.')
c = json.loads(path.read_text())['claudeAiOauth']
print(f'CLAUDE_CODE_OAUTH_TOKEN={c[\"accessToken\"]}')
print(f'CLAUDE_CODE_OAUTH_REFRESH_TOKEN={c[\"refreshToken\"]}')
" >> agent/.env
```

If your distribution stores credentials in a system secret manager (GNOME
Keyring, KWallet) instead of the JSON file, export them via that tool first
and adapt the snippet to read from `subprocess` output.

**Windows** (Credential Manager via PowerShell):

```powershell
$cred = Get-StoredCredential -Target "Claude Code-credentials"
$json = ConvertFrom-Json $cred.GetNetworkCredential().Password
"CLAUDE_CODE_OAUTH_TOKEN=$($json.claudeAiOauth.accessToken)"           | Out-File -Encoding utf8 -Append agent/.env
"CLAUDE_CODE_OAUTH_REFRESH_TOKEN=$($json.claudeAiOauth.refreshToken)"  | Out-File -Encoding utf8 -Append agent/.env
```

`Get-StoredCredential` requires the [`CredentialManager` module](https://www.powershellgallery.com/packages/CredentialManager).
If unavailable, open `Control Panel → User Accounts → Credential Manager →
Windows Credentials`, expand the `Claude Code-credentials` entry, and copy
the `accessToken` / `refreshToken` fields manually.

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

### Codex agent mode

To use the Codex CLI agent (`"agent_mode": "codex"` in your runner config), you need an OpenAI API key exported as `CODEX_API_KEY` so the Codex CLI running inside the container can authenticate.

**Step 1: Add your key to `agent/.env`**

```bash
echo CODEX_API_KEY="sk-..." >> agent/.env
```

`CODEX_API_KEY` is read separately from `OPENAI_API_KEY` — codex mode will not fall back to `OPENAI_API_KEY`, so set it explicitly even if you already have one configured for the custom agent.

**Step 2: Configure `runner_config.json`**

```json
{
  "agent_mode": "codex",
  "agent_image": "cybench/mobilecybench-codex:latest",
  "agent_timeout": 1800,
  "model": "gpt-5.5",
  "reasoning_effort": "high"
}
```

The Docker image is pulled automatically. `agent_timeout` controls how long (in seconds) the CLI is allowed to run (default: 1800). `model` and `reasoning_effort` are optional overrides forwarded to the Codex CLI; omit them to use the agent's defaults.

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
- To run experiments: `documentation/EXPERIMENTS.md`
- For troubleshooting: `documentation/TROUBLESHOOTING.md`
