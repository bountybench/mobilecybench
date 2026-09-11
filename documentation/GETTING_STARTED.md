# Getting Started

Zero-to-first-pass@1 quick start. Targets the probe-only redteam flow described in
[`README.md`](README.md). If you're new, read that page first.

## 1) System prerequisites

- Python 3.11 or 3.12 (3.13 not yet validated)
- Docker 24+ **with the Compose v2 plugin**. Docker Desktop on macOS/Windows bundles Compose; on Linux `apt install docker.io` does **not** include it, so install both: `sudo apt install docker.io docker-compose-v2`
- Node.js 18+ / `npm` (for the `claude setup-token` agent-auth step in §3)
- Java 17+ (some apps require Java 21 — see each app's `metadata.json`)
- [GitHub CLI](https://cli.github.com/) (`gh`), authenticated via `gh auth login` — required by the default `build_type: "download-apk"` to fetch APK bundles from GitHub releases. Set `MOBILECYBENCH_SKIP_GH_CHECK=1` to skip the `setup.sh` preflight if you only build from source or use `skip-apk`.
- `apktool`, `zip`, `sqlcipher` — used by the exploit-APK build and SQLCipher app probes. `setup.sh` auto-installs them (apt on Linux, Homebrew on macOS), which needs `sudo` on Linux; on no-sudo / non-apt / proxied hosts, install them yourself first.

Hardware: the Android emulator needs hardware virtualization (KVM on Linux,
Hypervisor.framework on macOS) — nested-virt cloud VMs must have it enabled.
Budget ≥ 16 GB RAM and ~50 GB free disk for the emulator + Docker images.

On Linux, your user also needs read/write access to `/dev/kvm`. On a fresh VM
that usually means joining the `kvm` group once: `sudo gpasswd -a "$USER" kvm`,
then log out and back in (group membership is only picked up by a new login).
Without it the emulator exits immediately at boot; the runner's `ProbeKVM` check
detects this and prints the same fix.

Windows: use WSL or Git Bash; the shell scripts assume a POSIX environment.

### Where to run

You can run this quick start on **either**:

- **A local machine** (macOS, or Linux with `/dev/kvm`) — skip the VM box below
  and continue at §2.
- **A single Google Cloud VM** — the setup we use for our own experiments. Do the
  one-time provisioning box below, then continue at §2 exactly as written.

> One VM runs **one experiment at a time** (the emulator/KVM is single-tenant per
> host). To run the 52-configuration grid in parallel across many nodes instead, use the
> Kubernetes path in [`infra/gke/README.md`](../infra/gke/README.md). The GKE path
> is purely a parallelism optimization — a single VM produces identical results,
> just serially.

#### Provision a GCE VM (skip if running locally)

Sizing — the numbers and why:

- **Machine type: `n2-standard-8` (8 vCPU / 32 GB), recommended.** One experiment
  requests 4 vCPU / 16 GB and may burst to 6 vCPU / 24 GB (the resource
  request/limit in `infra/gke/job-template.yaml`), so `-8` leaves headroom for the
  host OS, Docker, and the emulator. This is the same shape the GKE node pool uses.
- **Must be an N2 machine — nested virtualization is required and `N2D` does not
  support it.** `n2-standard-4` (4 vCPU / 16 GB) is the bare minimum that meets the
  request but has zero headroom above the burst limit, so it is not recommended;
  prefer `-8`. Scale by adding VMs, not by shrinking the machine.
- **`--enable-nested-virtualization` at create time** is what makes `/dev/kvm`
  appear on the guest. Without this flag the emulator cannot start.
- **Disk: ≥ 100 GB SSD** (`pd-ssd` or `pd-balanced`); the emulator + Docker images
  need ~50 GB, so give headroom. Our GKE nodes use 200 GB `pd-ssd`.
- **OS image: Ubuntu 22.04 LTS.**

```bash
export PROJECT_ID=your-gcp-project

gcloud compute instances create mobilecybench \
  --project="$PROJECT_ID" \
  --zone=us-central1-a \
  --machine-type=n2-standard-8 \
  --enable-nested-virtualization \
  --image-family=ubuntu-2204-lts --image-project=ubuntu-os-cloud \
  --boot-disk-size=200GB --boot-disk-type=pd-ssd
```

SSH in and confirm KVM is present:

```bash
gcloud compute ssh mobilecybench --zone=us-central1-a

# On the VM — /dev/kvm must exist (this is what nested virt provides):
ls -l /dev/kvm
```

Install the host toolchain (the equivalent of what a laptop already has):

```bash
sudo apt-get update
sudo apt-get install -y \
  docker.io docker-compose-v2 git python3-venv openjdk-17-jdk nodejs npm

# Let your user reach Docker and /dev/kvm without sudo, then re-load groups:
sudo usermod -aG docker,kvm "$USER"
newgrp docker   # or log out and back in so the new groups take effect
```

From here the VM is just a Linux host — **continue with §2 exactly as written.**
The committed `runner_config.json` already sets `emulator_display: "headless"`, so
nothing display-related needs changing on a machine with no monitor.

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
initializes every app's `codebase` submodule — that is 30 app codebases, so expect a
large, slow clone. To init only one app, use `--init-submodules <app_name>`, or drop the
flag entirely: `runner.py` auto-inits the codebase for whichever app you run.

We host the app environment source in our associated
[`cy-suite`](https://github.com/cy-suite) org, pulled in by the `codebase`
submodules.

Default Android SDK is 35. To target a different version, pass an app name and
`setup.sh` reads `sdk` from its `metadata.json`. Run `./setup.sh --help` for the full
app-to-SDK list.

## 3) Authenticate the agent

The benchmark uses **`agent_mode: "external"`** — a BYO Docker image carrying a coding-agent CLI
(claude-code, codex, opencode). First create your env file from the template, then
pick one agent and authenticate it via `agent/.env`:

```bash
cp agent/.env.example agent/.env                    # first time only
```

`model` and `reasoning_effort` are forwarded verbatim to the chosen CLI —
external mode has **no model allowlist**, so a model id never has to appear in
our examples or any registry of ours. To run a different model, just change the
`model` field:

- **Claude Code** passes it to `claude --model`, resolved by your Anthropic
  subscription — any Anthropic model id works as-is, no image change.
- **opencode** passes it to `opencode --model`. Built-in provider/model ids work
  as-is; for one opencode doesn't already know, add a custom provider config (see
  the opencode section below).

Change `agent_image` only to switch the agent CLI itself (claude-code, codex,
opencode) — the published tags are in the sections below.

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
  "agent_image": "cybench/mobilecybench:claudecode_2.1.170-r1",
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

### OpenCode (custom providers)

The opencode CLI supports any OpenAI-compatible provider via an inline config
passed through the `OPENCODE_CONFIG_CONTENT` env var. The harness forwards both
`OPENCODE_CONFIG_CONTENT` and provider-specific API-key envs into the agent
container.

Use this when the provider/model row is not yet in opencode's built-in
registry. Set the config and the provider key in `agent/.env`, then point
`runner_config.json` at the model id:

```bash
echo "OPENCODE_CONFIG_CONTENT=$(cat documentation/opencode_provider_examples/together_glm52.json)" >> agent/.env
echo 'TOGETHER_API_KEY=<paste>'                                                                  >> agent/.env
```

```jsonc
{
  "agent_mode": "external",
  "agent_image": "cybench/mobilecybench:opencode_1.15.6-r1",
  "model": "togetherai/zai-org/GLM-5.2",
  "reasoning_effort": "max"
}
```

If your provider's key env is not already forwarded, add it to
`AUTH_ENV_PASSTHROUGH` in `agent/runtime/container.py`.

### Other BYO

Build an image that satisfies the BYO contract (see [`supplemental/BRING_YOUR_OWN_AGENT.md`](supplemental/BRING_YOUR_OWN_AGENT.md)) and point `agent_image` at it.

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

To run the active app set sequentially instead, use the batch config:

```bash
python runner.py --config runner_config_batch.json
```

`runner.py` is still the user-facing command; `batch_runner.py` is only the
internal module that expands the matrix and runs each batch job.

`runner_config_batch.json` uses the same top-level fields as
`runner_config.json`, plus a `batch` block that selects apps and matrix fields.
The committed batch config has `batch.apps: "in_scope"`, so it reads the active
app list from [`apps/app_catalog.json`](../apps/app_catalog.json):`sets.in_scope`
in this checkout and runs the full grid by default: both attack settings × both
access levels (source-visible vs. APK-only) = 13 apps × 2 × 2 = 52
configurations for one agent. `continue_on_failure` records a failed run and
moves on; it does not retry failed runs.

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
"attacker_model": "remote_attacker",  // or "malicious_app" — the attack setting
"no_codebase":    false,              // true = APK-only leg
"apk_obfuscation":"off"               // "on" when no_codebase=true and the app has download_link_obfuscated
```

See [`README.md`](README.md#2-attack-setting--access-level--the-ablation) for the matrix
overview, and [`EXPERIMENTS.md § Attack setting`](EXPERIMENTS.md#attack-setting) for what
each attack setting means at the implementation level.

## Where to go next

- Configure an experiment, interpret results: [`EXPERIMENTS.md`](EXPERIMENTS.md)
- Debug a stuck setup: [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md)

Extending the benchmark (new app, new model, new BYO agent image) — see the
reference docs in [`supplemental/`](supplemental/).
