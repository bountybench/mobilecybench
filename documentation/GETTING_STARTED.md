# Getting Started

Zero-to-first-pass@1 quick start. Targets the probe-only redteam flow described in
[`README.md`](README.md). If you're new, read that page first.

## 1) System prerequisites

- Python 3.11 or 3.12 (3.13 not yet validated)
- Docker Desktop (for the agent stack and most app backends)
- Java 17+ (some apps require Java 21 — see each app's `metadata.json`)
- [GitHub CLI](https://cli.github.com/) (`gh`), authenticated via `gh auth login` — required by the default `build_type: "download-apk"` to fetch APK bundles from GitHub releases. Set `MOBILECYBENCH_SKIP_GH_CHECK=1` to skip the `setup.sh` preflight if you only build from source or use `skip-apk`.

Windows: use WSL or Git Bash; the shell scripts assume a POSIX environment.

## 2) Clone + Python env + setup script

```bash
git clone https://github.com/bountybench/mobilecybench
cd mobilecybench
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
bash setup.sh --init-submodules
```

`setup.sh` installs the Android SDK + emulator and creates the AVD. `--init-submodules`
initializes every app's `codebase` submodule. To init only one app, use
`--init-submodules <app_name>`.

Default Android SDK is 35. To target a different version, pass an app name and
`setup.sh` reads `sdk` from its `metadata.json`. Run `./setup.sh --help` for the full
app-to-SDK list.

## 3) Authenticate the agent

The benchmark uses **`agent_mode: "external"`** — a BYO Docker image carrying a coding-agent CLI
(claude-code, codex, opencode). Pick one and authenticate it via `agent/.env`:

### Claude Code (recommended)

Works with an Anthropic Claude subscription (Pro / Max / Team / Enterprise). Generate a
long-lived OAuth token once:

```bash
npm install -g @anthropic-ai/claude-code
claude setup-token
echo 'CLAUDE_CODE_OAUTH_TOKEN=<paste>' >> agent/.env
```

`claude setup-token` mints a long-lived (~1 year) OAuth token; the harness
forwards `CLAUDE_CODE_OAUTH_TOKEN` into the agent container and the in-container
CLI reads it directly. Independent of your interactive `claude` sessions.

In `runner_config.json`:

```jsonc
{
  "agent_mode": "external",
  "agent_image": "cybench/mobilecybench:claudecode_2.1.156-r1",
  "model": "claude-opus-4-8",
  "reasoning_effort": "max"
}
```

### Codex

```bash
echo 'OPENAI_API_KEY=sk-...' >> agent/.env
```

```jsonc
{
  "agent_mode": "external",
  "agent_image": "cybench/mobilecybench:codex_0.130.0-r2",
  "model": "gpt-5.5",
  "reasoning_effort": "high"
}
```

### Other BYO

Build an image that satisfies the BYO contract (see [`archive/BRING_YOUR_OWN_AGENT.md`](archive/BRING_YOUR_OWN_AGENT.md)) and point `agent_image` at it.

## 4) Run a baseline experiment

Make sure no emulator is already running (the runner manages its own lifecycle):

```bash
./stop_emulator.sh
```

The committed `runner_config.json` ships a probe-only example. Pick an app from the
[curated list in `README.md`](README.md#3-apps-in-scope) and run:

```bash
python runner.py audiobookshelf --config runner_config.json
```

What happens next:

1. APK is downloaded (`build_type: download-apk`).
2. Emulator starts and the app is installed.
3. Backend services start.
4. Agent container boots, agent runs under its wallclock budget.
5. Probe replay fires; verdict is written to `apps/<app>/redteam_scores.json`.
6. Emulator and containers tear down. Per-run logs land in `logs/<run-id>/`.

Result snapshot to look at first: `logs/<run-id>/run_summary.json`. `outcome` +
`exit_reason` + `results.status` + `results.score` are the four fields to read.

## 5) The 2×2 ablation

Flip these two fields in `runner_config.json` to step through the matrix:

```jsonc
"attacker_model": "remote_attacker",  // or "malicious_app"
"no_codebase":    false,              // true = apk_only leg
"apk_obfuscation":"off"               // "on" when no_codebase=true and the app has download_link_obfuscated
```

See [`README.md`](README.md#2-attacker-model--access-mode--the-ablation) for the matrix
overview, and [`EXPERIMENTS.md § Threat model`](EXPERIMENTS.md#threat-model) for what
each attacker model means at the implementation level.

## Where to go next

- Configure an experiment, interpret results: [`EXPERIMENTS.md`](EXPERIMENTS.md)
- Debug a stuck setup: [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md)

Extending the benchmark (new app, new model, new BYO agent image) — see the
maintainer docs in [`archive/`](archive/).
