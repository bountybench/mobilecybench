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

## Prerequisites

- Python 3.11 or 3.12 (3.13 not yet validated for agent dependencies)
- Docker 24+ — Docker Desktop on macOS/Windows, Docker Engine on Linux
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
