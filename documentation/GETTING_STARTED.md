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
bash setup.sh --init-submodules
```

`--init-submodules` initializes all app codebases plus the `zerodays/` task bundle. To init only one app, use `--init-submodules <app_name>` (e.g. `conversations`).

Windows note: `setup.sh` and the emulator scripts require WSL or Git Bash. Use the Windows venv activation line above.

To run the AI agent, provide an API key. The built-in models cover three providers (see `agent/custom/model_providers/factory.py:SupportedModel` for the full list, including older entries kept for backwards compatibility):

- **OpenAI** (Responses API) — `gpt-5.5`, `gpt-5.5-pro`; `gpt-5.4`, `gpt-5.4-pro`, `gpt-5.2`, `gpt-5.2-pro`, `gpt-5.2-codex`. Requires `OPENAI_API_KEY`.
- **Anthropic** (via LiteLLM) — `claude-opus-4-7`, `claude-sonnet-4-6`, `claude-haiku-4-5`; `claude-opus-4-6`, `claude-sonnet-4-5-20250929`. Requires `ANTHROPIC_API_KEY`.
- **Google** (via LiteLLM) — `gemini-3.1-pro`; `gemini-3-pro-preview`. Requires `GEMINI_API_KEY`.

To add a new model, append an entry to `SupportedModel` and a pricing row to `utils/token_pricing.json` — see [Adding a New Model](ADDING_MODELS.md). For one-off model-sweep exploration where cost telemetry doesn't matter, set `"allow_unregistered_models": true` in `runner_config.json` to bypass the registry.

```bash
echo OPENAI_API_KEY=sk-... > agent/.env
python runner.py owncloud-android
```

> The committed `runner_config.json` is a probe-only example (probe_only + malicious_app), which requires the target app to ship per-app probes and `generic_probe_config.json`. `owncloud-android` is one of the apps that satisfies this.

**Important:** Do not start the emulator manually before running `runner.py` — it manages its own emulator lifecycle (start, install, cleanup) and will fail if one is already running. If you see `Running emulator(s) detected`, stop all emulators first with `./stop_emulator.sh`.

For the workflow / task type / attacker model axes that define a run, see the README. This guide focuses on the setup steps below; once the environment is healthy, `documentation/EXPERIMENTS.md` walks through configuring those axes for an actual run and `documentation/REDTEAM.md` covers redteam scoring.

If you do not want to use an API key, run in dry-run mode instead:

```bash
python runner.py conversations --config runner_config_dryrun.json
```

## 1) System prerequisites

- Python 3.11 or 3.12 (3.13 not yet validated for agent dependencies)
- Docker Desktop (for agent stack and some app environments)
- Java (required for Android builds; setup.sh enforces OpenJDK 17+. Please note that some apps require Java 21 to build.)
- [GitHub CLI](https://cli.github.com/) (`gh`), authenticated with `gh auth login` — required by the default `build_type: "download-apk"` to fetch APK bundles from GitHub releases. Set `MOBILECYBENCH_SKIP_GH_CHECK=1` to skip the `setup.sh` preflight if you only build from source or use `skip-apk`.

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

- Default SDK is 35. To target a different version, pass an app name and `setup.sh` reads `sdk` from its `metadata.json` (example: `./setup.sh owncloud-android` installs SDK 34). Run `./setup.sh --help` for the full app list with their SDK pinning.
- `setup.sh` installs Android SDK packages and creates the AVD.
- To initialize submodules during setup, use `--init-submodules` (all) or `--init-submodules <app_name>` (single app).
- `setup.sh` installs `apktool` if it is missing.

## 4) Obtain API key(s)

To run the agent, an API key is required in a `.env` file in the `agent/` directory. Supported model providers are listed in `agent/custom/model_providers/factory.py`.

```bash
cd agent && touch .env
echo OPENAI_API_KEY="sk..." >> .env
```

(Use `>>`, not `>` — `>` overwrites any existing keys.)

### External agents (Claude Code, Codex, BYO)

Set `"agent_mode": "external"` and name the image in `"agent_image"`. The harness delivers `/app/task.json` and reads back `/app/agent_run/` + `/app/agent_exploit/`. Full contract: [BRING_YOUR_OWN_AGENT.md](BRING_YOUR_OWN_AGENT.md).

#### Claude Code reference image

mobilecybench supports authentication with a Claude subscription (Pro / Max / Team / Enterprise).

**Step 1: Install Claude Code**

```bash
npm install -g @anthropic-ai/claude-code
```

**Step 2: Generate a long-lived OAuth token**

Run [`claude setup-token`](https://code.claude.com/docs/en/authentication#generate-a-long-lived-token) to mint a token scoped for headless / CI use. It is valid for ~1 year and independent of your interactive `claude` sessions.

```bash
claude setup-token
echo 'CLAUDE_CODE_OAUTH_TOKEN=<paste-token-here>' >> agent/.env
```

The harness forwards `CLAUDE_CODE_OAUTH_TOKEN` into the container; the in-container CLI reads it directly. No credentials file is written.

**Step 3: Configure `runner_config.json`**

```json
{
  "agent_mode": "external",
  "agent_image": "cybench/mobilecybench:claudecode_2.1.140-r2",
  "model": "claude-sonnet-4-6",
  "agent_wallclock_seconds": 1800
}
```

`agent_wallclock_seconds` is the harness-side SIGKILL deadline (default 1800).

#### Codex reference image

Set `OPENAI_API_KEY` in `agent/.env`. The image's `/run-agent.sh` pipes it into `codex login --with-api-key` before invoking the CLI.

```bash
echo OPENAI_API_KEY="sk-..." >> agent/.env
```

```json
{
  "agent_mode": "external",
  "agent_image": "cybench/mobilecybench:codex_0.130.0-r2",
  "model": "gpt-5.5",
  "reasoning_effort": "high",
  "agent_wallclock_seconds": 1800
}
```

#### Lab BYO

Build an image satisfying the BYO contract and point `agent_image` at it. See [BRING_YOUR_OWN_AGENT.md](BRING_YOUR_OWN_AGENT.md) for the Dockerfile + `/run-agent.sh` template and task.json schema.

## 5) Pick an app

List available apps:

```bash
ls apps
```

Pick an app that ships per-app probes and `generic_probe_config.json`. The committed `runner_config.json` defaults to probe-only + `malicious_app`; `owncloud-android` is a known-supported choice.

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
python runner.py conversations --config runner_config_dryrun.json
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
