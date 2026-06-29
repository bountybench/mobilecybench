# MobileCyBench

MobileCyBench measures AI agent cybersecurity capabilities. Each experiment
puts a coding agent in a realistic environment — a working Android app and its
backend running in an emulator — and asks it to find and exploit a
vulnerability. Detection is automatic: each app ships CIA
(confidentiality / integrity / availability) probes that fire when the agent
takes an action it shouldn't be able to.

Probes are derived from each app's golden flow. We model what the agent's
account is *legitimately* allowed to do under the app's permissions, then
place probes at the boundary — so any action that crosses it trips a signal.

> Start at [**`documentation/README.md`**](documentation/README.md) for the
> curated app list, the source-vs-`apk_only` ablation, and links to the rest
> of the docs.

## TL;DR run commands

You can run either one app with the normal runner config:

```bash
python runner.py <app> --config runner_config.json
```

Or run the active app set sequentially with a batch config:

```bash
python runner.py --config runner_config_batch.json
```

`runner.py` is still the only user-facing runner command. `batch_runner.py` is
an internal orchestration module that `runner.py` calls when the config contains
a top-level `batch` block.

`runner_config_batch.json` is the batch equivalent of `runner_config.json`: the
top-level fields are normal runner defaults (`workflow`, `model`,
`agent_image`, token limits, etc.), and the `batch` block selects apps and
matrix fields. By default, `batch.apps: "in_scope"` reads the active app list
from [`apps/app_catalog.json`](apps/app_catalog.json):`sets.in_scope` in this
checkout and runs the full grid: both `attacker_model` values × both
visibility modes (source vs `apk_only`). `network_mode` and `apk_obfuscation`
are coupled to visibility via `batch.matrix` + `batch.exclude` to match the
paper conditions (source → `permissive` / obfuscation `off`; `apk_only` →
`restricted` / obfuscation `on`), giving 13 apps × 2 × 2 = 52 cells.
`continue_on_failure` means
"record a failed cell and continue"; it does not retry failed cells. For more
detail, see
[`documentation/EXPERIMENTS.md`](documentation/EXPERIMENTS.md#run-a-sequential-batch).

## Prerequisites

- Python 3.11 or 3.12 (3.13 not yet validated for agent dependencies)
- Docker 24+ with the Compose v2 plugin — Docker Desktop (macOS/Windows) bundles it; on Linux `apt install docker.io` does **not**, so install both: `sudo apt install docker.io docker-compose-v2`
- Node.js 18+ / `npm` (for the `claude setup-token` agent-auth step below)
- Java 17+ (some apps require Java 21 — see each app's `metadata.json`)
- [GitHub CLI](https://cli.github.com/) (`gh`), authenticated with `gh auth login` — required by `build_type: "download-apk"` to fetch APK bundles. Set `MOBILECYBENCH_SKIP_GH_CHECK=1` to skip the `setup.sh` preflight if you only build from source or use `skip-apk`.

Hardware: the Android emulator needs hardware virtualization (KVM on Linux,
Hypervisor.framework on macOS) — nested-virt cloud VMs must have it enabled.
Budget ≥ 16 GB RAM and ~50 GB free disk for the emulator + Docker images.

Windows: use WSL or Git Bash; the shell scripts assume a POSIX environment.

## Quick start

```bash
git clone https://github.com/bountybench/mobilecybench
cd mobilecybench
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
bash setup.sh --init-submodules
```

Authenticate the agent (Claude Code is the default — see [GETTING_STARTED.md § 3](documentation/GETTING_STARTED.md#3-authenticate-the-agent) for codex/opencode alternatives):

```bash
cp agent/.env.example agent/.env                    # first time only
npm install -g @anthropic-ai/claude-code
claude setup-token
echo 'CLAUDE_CODE_OAUTH_TOKEN=<paste>' >> agent/.env
```

Then run a probe-only experiment against any curated app:

```bash
./stop_emulator.sh                                  # ensure none is running
python runner.py audiobookshelf --config runner_config.json
```

Or run the active app set sequentially:

```bash
./stop_emulator.sh
python runner.py --config runner_config_batch.json
```

Results land in `logs/<run-id>/run_summary.json`.

## Documentation

Four docs cover the bench-run path end-to-end. The full index is at
[`documentation/README.md`](documentation/README.md).

- [Documentation index + curated app list + ablation overview](documentation/README.md)
- [Getting Started](documentation/GETTING_STARTED.md) — setup + first run
- [Experiments](documentation/EXPERIMENTS.md) — `runner_config.json` reference, pipeline stages, result schema, status codes, MA permission gate
- [Troubleshooting](documentation/TROUBLESHOOTING.md) — common issues

Maintainer-facing material (adding apps / models, BYO agent contracts, GKE
deployment, CI mechanics, command cheatsheets, deep architecture notes) lives
in [`documentation/archive/`](documentation/archive/) — kept for reference but
not needed to run an experiment.

GKE-specific setup (running at scale): [`infra/gke/README.md`](infra/gke/README.md).
