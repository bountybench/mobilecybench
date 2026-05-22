# Running MobileCybench on a Google Cloud VM

This guide walks through provisioning a Google Cloud Compute Engine VM and running a probe-only `conversations` evaluation end-to-end with `gpt-5.5`. Every step has an explicit validation check so you can isolate failures before they cascade.

The configuration here is intentionally minimal — single app, probe-only, no GPU, no custom firewall — to make the first run reproducible. Once it works, swap in your real workflow.

## Contents

1. [What you'll run](#what-youll-run)
2. [Prerequisites](#prerequisites)
3. [Step 1 — Provision the VM](#step-1--provision-the-vm)
4. [Step 2 — Verify nested virtualization](#step-2--verify-nested-virtualization)
5. [Step 3 — Install system dependencies](#step-3--install-system-dependencies)
6. [Step 4 — Authenticate the GitHub CLI](#step-4--authenticate-the-github-cli)
7. [Step 5 — Clone the repo and install Python deps](#step-5--clone-the-repo-and-install-python-deps)
8. [Step 6 — Configure and verify the OpenAI key](#step-6--configure-and-verify-the-openai-key)
9. [Step 7 — Initialize submodules](#step-7--initialize-submodules)
10. [Step 8 — Smoke-test the app's Docker stack](#step-8--smoke-test-the-apps-docker-stack)
11. [Step 9 — Smoke-test the Android emulator](#step-9--smoke-test-the-android-emulator)
12. [Step 10 — Dry-run the runner](#step-10--dry-run-the-runner)
13. [Step 11 — Real run](#step-11--real-run)
14. [Snapshot for fast re-runs](#snapshot-for-fast-re-runs)
15. [Tear down](#tear-down)
16. [Troubleshooting reference](#troubleshooting-reference)

---

## What you'll run

```bash
python runner.py conversations
```

With the repo's committed `runner_config.json`:

| Field | Value | Implication |
|---|---|---|
| `workflow` | `redteam` | Score via app probes, not a verifier script |
| `probe_only` | `true` | Single-baseline pass; no patch-differential replay |
| `attacker_model` | `malicious_app` | Agent builds an exploit APK |
| `build_type` | `download-apk` | Fetch the released APK bundle (no source build) |
| `network_mode` | `permissive` | No in-container egress firewall |
| `model` | `gpt-5.5` | OpenAI Responses API |
| `max_iterations` | `30` | Agent step budget per run |

A successful run produces a per-run directory under `logs/` containing `run_summary.json`, and updates `apps/conversations/redteam_scores.json`.

For a full description of the workflow axes, see [`documentation/REDTEAM.md`](documentation/REDTEAM.md) and [`documentation/EXPERIMENTS.md`](documentation/EXPERIMENTS.md).

---

## Prerequisites

Before starting:

- A Google Cloud project with **billing enabled** and the **Compute Engine API** enabled.
- `gcloud` CLI installed locally and authenticated (`gcloud auth login`, `gcloud config set project <PROJECT_ID>`).
- A region/zone that supports nested virtualization. All public GCP zones support it on the required machine families; the examples use `us-central1-a`.
- An **OpenAI API key** with access to `gpt-5.5`. (To use a different provider, see "Switching providers" at the bottom.)
- A **GitHub personal access token** with `repo` scope. The default `build_type: download-apk` fetches the APK bundle from a release in `bountybench/mobilecybench` and requires `gh` to be authenticated.

**Cost estimate.** A `c3-standard-8` instance is roughly **$0.39/hour** in `us-central1` (on-demand, sustained-use discounts apply automatically). A 100 GB pd-balanced boot disk is about **$10/month**. Stop the VM between runs — you'll pay only for the disk.

**Long-running sessions.** Use `tmux` or `screen` once you're on the VM. A full agent run can take 20–60 minutes; an SSH disconnect will kill it otherwise.

---

## Step 1 — Provision the VM

The machine type and image are chosen deliberately:

- **`c3-standard-8`** (8 vCPU, 32 GB RAM): the `c3`, `c2`, `n2`, and `n2d` families support nested virtualization, which the Android emulator needs for KVM acceleration. `c3` gives the best per-core performance for emulator boot and APK compilation.
- **Ubuntu 24.04 LTS**: Python 3.12 is the system default and is validated for the agent dependencies (Python 3.13 is not yet validated, per the project README).
- **100 GB pd-balanced**: Docker images (Kali agent + per-app containers) plus the Android SDK plus APK bundles together consume ~30–50 GB. 100 GB leaves room for logs and snapshots.

```bash
gcloud compute instances create mcb-conv-1 \
  --zone=us-central1-a \
  --machine-type=c3-standard-8 \
  --enable-nested-virtualization \
  --image-family=ubuntu-2404-lts-amd64 --image-project=ubuntu-os-cloud \
  --boot-disk-size=100GB --boot-disk-type=pd-balanced \
  --metadata=enable-oslogin=TRUE
```

> `--enable-nested-virtualization` **must** be passed at create time. It cannot be enabled later without recreating the VM.

### Check 1a — SSH reaches the VM

```bash
gcloud compute ssh mcb-conv-1 --zone=us-central1-a --command='echo OK_$(hostname)_$(date +%s)'
```

**Pass:** prints `OK_mcb-conv-1_<unix-timestamp>` within ~30 seconds.
**Fail:** If the first attempt fails with return code 255 immediately after VM creation, wait ~20 seconds and retry — OS Login key propagation can lag the instance becoming `RUNNING`. If it still fails after a minute, check that the `default-allow-ssh` firewall rule allows TCP/22 from your IP (it does by default in fresh projects).

### Check 1b — VM has internet egress

```bash
gcloud compute ssh mcb-conv-1 --zone=us-central1-a --command='curl -sS -o /dev/null -w "%{http_code}\n" https://api.github.com'
```

**Pass:** `200`.
**Fail:** `000` or timeout means egress is blocked by a VPC firewall or routes. Egress to GitHub, Docker Hub, OpenAI, and Google APIs is required.

---

## Step 2 — Verify nested virtualization

Connect to the VM (`gcloud compute ssh mcb-conv-1 --zone=us-central1-a`) and run:

```bash
sudo apt-get update -qq && sudo apt-get install -y cpu-checker
kvm-ok && ls -l /dev/kvm
```

**Pass:** `kvm-ok` reports **"KVM acceleration can be used"** *and* `/dev/kvm` exists (`crw-rw---- 1 root kvm ...`).
**Fail:** the VM does not have KVM. Delete it and recreate with `--enable-nested-virtualization`. Do not continue — without KVM the Android emulator runs in pure software mode (TCG), which takes ~30 minutes to boot a single image and makes the benchmark unusable.

---

## Step 3 — Install system dependencies

```bash
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
  python3.12-venv python3-pip git openjdk-17-jdk \
  unzip zip curl jq tmux
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"
sudo usermod -aG kvm "$USER"      # required for the Android emulator (Step 9)
git config --global user.email "mcb-vm@example.com"
git config --global user.name  "MobileCybench VM"   # the runner runs `git commit` (Step 10)
```

The two `usermod` calls add your user to the `docker` and `kvm` groups. Each `gcloud compute ssh` invocation creates a fresh session that picks up the new memberships automatically; long-lived `ssh` sessions need to `exit` and reconnect first.

The `git config` lines set a global identity. The runner stages each app's codebase into a fresh git repo and runs `git commit -m 'Initial commit'`; on a fresh VM this fails with exit 128 (`Author identity unknown`) unless a global identity is set.

### Check 3a — toolchain versions

```bash
python3 --version              # Python 3.12.x
java -version 2>&1 | head -1   # openjdk version "17.x"
docker --version               # Docker 28.x or newer
```

### Check 3b — Docker daemon usable without sudo

```bash
docker run --rm hello-world | grep -q 'Hello from Docker' && echo PASS
```

**Pass:** `PASS`.
**Fail (`permission denied on /var/run/docker.sock`):** the docker group change has not been picked up by your shell. Fully disconnect (`exit` until the SSH connection closes) and reconnect — `newgrp docker` is not sufficient because the runner spawns subprocesses that inherit the original group set.

---

## Step 4 — Authenticate the GitHub CLI

`gh` is required because `build_type: "download-apk"` (the committed default) fetches APK bundles from GitHub release assets. The preflight in `setup.sh` will fail otherwise.

```bash
sudo apt-get install -y gh
gh auth login   # HTTPS protocol; paste a PAT with `repo` scope
```

### Check 4 — `gh` is authenticated and the release is reachable

```bash
gh auth status
gh release view apk-conversations-v2 \
  -R bountybench/mobilecybench \
  --json assets -q '.assets[].name'
```

**Pass:** `apk-bundle.zip` is printed.
**Fail (HTTP 404):** the PAT lacks access. If your token cannot be granted access to the release, you can bypass the `gh` preflight with `export MOBILECYBENCH_SKIP_GH_CHECK=1` — but then you must also build the APK locally by setting `build_type` to something other than `download-apk` (see [`documentation/EXPERIMENTS.md`](documentation/EXPERIMENTS.md)).

---

## Step 5 — Clone the repo and install Python deps

```bash
gh auth setup-git                         # configures git to use the gh PAT for HTTPS
gh repo clone bountybench/mobilecybench   # repo is private; plain `git clone` will fail
cd mobilecybench
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

The dependency install also installs `litellm`, which will print two `WARNING` lines about missing `botocore` (Bedrock/SageMaker stream shapes). These are harmless when not using AWS providers.

### Check 5 — `runner.py` imports cleanly

```bash
python -c "import runner; print('IMPORT_OK')"
```

**Pass:** `IMPORT_OK`.
**Fail:** typically a transient pip resolver issue. Re-run `pip install -r requirements.txt`; if it persists, capture the traceback and check `documentation/TROUBLESHOOTING.md`.

---

## Step 6 — Configure and verify the OpenAI key

Validate the key *before* you spend time on emulator and Docker setup — a bad key won't surface until the agent's first model call, late in the run.

```bash
echo "OPENAI_API_KEY=sk-..." > agent/.env
chmod 600 agent/.env
```

### Check 6 — key is valid and `gpt-5.5` is reachable

```bash
set -a; source agent/.env; set +a
curl -sS https://api.openai.com/v1/models/gpt-5.5 \
  -H "Authorization: Bearer $OPENAI_API_KEY" | jq -r '.id // .error.message'
```

**Pass:** prints `gpt-5.5`.
**Fail:** any other output. Common cases:

- `Invalid API key` — typo, wrong project, or revoked key.
- `The model 'gpt-5.5' does not exist or you do not have access to it.` — your organization is not enabled for this model. Choose an alternative from `agent/custom/model_providers/factory.py:SupportedModel` and update `runner_config.json:model` accordingly.

---

## Step 7 — Initialize submodules

```bash
source .venv/bin/activate          # required: setup.sh pip-installs into the active venv
bash setup.sh
git submodule update --init apps/conversations/codebase
```

`setup.sh` bootstraps the Android SDK under `~/.android-sdk`, creates AVDs for SDK 33/34/35 (`conversations` uses 35), and validates the host environment. It is idempotent and takes ~3 minutes on first run because the system image download is large.

`setup.sh` does **not** install `build-tools`, which the `malicious_app` attacker model needs to build the agent's exploit APK on the host. Without it, the first agent iteration fails with `APK build failed (exit 2): ls: cannot access '~/.android-sdk/build-tools'` and the run is marked invalid. Install it now:

```bash
export ANDROID_HOME="$HOME/.android-sdk"
export PATH="$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
yes | sdkmanager "build-tools;35.0.0"
```

Use the version matching the app's `sdk` field in `apps/<app>/metadata.json` (`conversations` declares `sdk: "35"`).

The `git submodule update` line above pulls only the `conversations` app's source — there is no need to fetch every app's codebase to run this single benchmark. `sdkmanager` will fill the terminal with progress-bar output during the build-tools download (~30 seconds); this is expected.

> On Ubuntu 24.04, **`setup.sh` must be run with the venv activated**. Otherwise its pip step fails with `error: externally-managed-environment` (PEP 668).

> **`zip` is also required**, not just `unzip`. The agent's `build_exploit_apk.sh` script invokes plain `zip` to add `classes.dex` into the APK. The script silently swallows the error if `zip` is missing (the `cd && zip && cd -` chain prevents `set -e` from triggering), producing an APK that lacks compiled code. The result: every agent attempt fails at the verifier with `INSTALL_FAILED_INVALID_APK: ... code is missing`. Step 3 above installs both `zip` and `unzip` — do not omit either.

### Check 7 — submodule populated

```bash
test -e apps/conversations/codebase/.git && \
  test -n "$(ls apps/conversations/codebase)" && echo SUBMODULE_OK
```

**Pass:** `SUBMODULE_OK`. (In a git submodule, `.git` is a *file* pointing to the parent's `.git/modules/...`, not a directory — so `test -e` is the correct check.)

The APK bundle is fetched lazily by the runner on first use; no separate check is needed here.

### Probe-only requires a `generic_probe_config.json`

The committed `runner_config.json` runs in probe-only mode, which requires `apps/conversations/generic_probe_config.json`. This file is **not currently checked in** (an upstream gap — file an issue if you hit this). Create it manually:

```bash
cat > apps/conversations/generic_probe_config.json <<'EOF'
{
  "version": 1,
  "generic_probe_applicability": {
    "access.ssrf_detected": true,
    "confidentiality.secrets": true,
    "confidentiality.app_flag": true,
    "confidentiality.container_flag": true,
    "integrity.app_flag": true,
    "integrity.app_pwned_file": true,
    "integrity.container_flag": true,
    "integrity.container_pwned_file": true,
    "availability.check_container_health": true
  }
}
EOF
```

The field names map to the generic probe checks in `apps/conversations/test_*.py`. If a check doesn't apply to your app, set its value to `false`.

---

## Step 8 — Smoke-test the app's Docker stack

`conversations` ships with an XMPP server (`prosody`) that runs as a sidecar container. Bringing it up in isolation now means a later runner failure can be unambiguously attributed to the agent/emulator path rather than the app's services.

The app's `docker-compose.yml` declares two **external** networks (`shared_net`, `agent_net`) that the runner normally creates before invoking the app. To smoke-test the app standalone, create them ahead of time and remove them after:

```bash
docker network create shared_net
docker network create agent_net
cd apps/conversations
docker compose up -d         # builds the prosody image on first run (~30s)
docker ps --filter name=conversations-prosody --format '{{.Names}} {{.Status}}'
docker compose down
cd ../..
docker network rm shared_net agent_net
```

**Pass:** `conversations-prosody Up ...` appears in the `docker ps` output.
**Fail:** inspect logs with `docker compose logs` (from inside `apps/conversations/`). Most failures are TLS/config issues in `prosody.cfg.lua` or `secrets.json`; re-clone the repo if either was corrupted.

---

## Step 9 — Smoke-test the Android emulator

`start_emulator.sh` blocks until the emulator finishes booting (it prints `Emulator ready: emulator-5554` then exits 0). No backgrounding or polling loop is needed — just run it in the foreground.

```bash
# SDK 35 matches the conversations app.
# start_emulator.sh auto-detects headless mode when $DISPLAY is unset (cloud VMs).
timeout 300 ./start_emulator.sh 35 && echo EMULATOR_BOOT_OK || echo EMULATOR_BOOT_FAIL
adb devices
adb shell getprop ro.build.version.sdk
./stop_emulator.sh
```

**Pass:**

- `Emulator ready: emulator-5554` followed by `EMULATOR_BOOT_OK` within ~3 minutes.
- `adb devices` lists one device in state `device` (not `offline`).
- `ro.build.version.sdk` prints `35`.

**Fail:**

- Boot timeout almost always means KVM is not available — go back to Step 2.
- If you see `ProbeKVM: This user doesn't have permissions to use KVM (/dev/kvm)`, your user is missing from the `kvm` group. On a fresh GCP Ubuntu 24.04 image this group exists but no user is a member of it. Fix once with:
  ```bash
  sudo usermod -aG kvm "$USER"
  ```
  Each subsequent `gcloud compute ssh` will see the new group; long-lived `ssh` sessions need to reconnect.
- If you forgot to install the Android SDK env vars (`ANDROID_HOME`, PATH additions), `start_emulator.sh` will fail with `No such file or directory: 'adb'`. `setup.sh` writes them to `~/.bashrc`, but non-interactive `gcloud compute ssh --command` sessions don't source it. Either prepend `export ANDROID_HOME="$HOME/.android-sdk" && export PATH="$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$PATH" && ` to one-liners, or use a `tmux`/`bash -l` interactive session where `.bashrc` is sourced automatically.

> **Important:** always `./stop_emulator.sh` before invoking `runner.py`. The runner manages its own emulator lifecycle and will refuse to start if one is already running.

---

## Step 10 — Dry-run the runner

The dry-run config spins up the full runtime — emulator, app containers, Kali agent container — but drops you into an interactive shell instead of invoking the model. No tokens are spent.

One prerequisite specific to this step: **override `emulator_display` to `headless`.** `runner_config_dryrun.json` ships with `emulator_display: "headed"`, which fails on a headless VM. Either edit the file, or pass an override:

```bash
jq '.emulator_display = "headless"' runner_config_dryrun.json > /tmp/dryrun_headless.json
```

(The other one-time fix — global git identity for the runner's internal `git commit` — is already covered in Step 3.)

Pre-pull the Kali agent image once to avoid a long pause in the middle of the dry-run:

```bash
docker pull cybench/mobilecybench:latest
```

Then run the dry-run. To exit non-interactively (e.g. from a script), pipe `exit` to stdin:

```bash
# Interactive shell (recommended for first-time validation):
python runner.py conversations --config /tmp/dryrun_headless.json
# ... type `exit` when you see the `kali> ` prompt.

# Non-interactive variant for CI / automation:
echo exit | python runner.py conversations --config /tmp/dryrun_headless.json
```

Total run time on a freshly-pulled image: ~4 minutes (emulator boot dominates).

**Pass:** the log ends with `Interactive shell exited`, followed by cleanup messages and `Deleted agent_codebase`. The exit code is `0`.
**Fail:** the error message identifies which subsystem regressed. If you reached this point with Steps 8 and 9 passing, the most likely culprit is git config (Step 10.1 above) or the Kali image (refresh with `docker pull cybench/mobilecybench:latest`).

---

## Step 11 — Real run

The committed `runner_config.json` also has `emulator_display: "headed"`. As in Step 10, override it for headless VMs:

```bash
jq '.emulator_display = "headless"' runner_config.json > /tmp/runner_config_headless.json
python runner.py conversations --config /tmp/runner_config_headless.json
```

Alternatively, edit `runner_config.json` in place. Expect a runtime of 15–45 minutes depending on emulator boot time and how many agent iterations are consumed (probe-only with the default 30-iteration budget).

> Use `tmux` so an SSH disconnect doesn't kill the run:
> ```bash
> tmux new -s mcb
> # ... start the run ...
> # detach with Ctrl-b d; reattach with `tmux attach -t mcb`
> ```

### Check 11 — the run produced a summary

```bash
LATEST=$(ls -1t logs/ | head -1)
jq '.status, .scores' "logs/$LATEST/run_summary.json"
cat apps/conversations/redteam_scores.json
```

**Pass:** `run_summary.json` exists with a non-null `status`; `redteam_scores.json` reflects the new run.
**Fail:** the run wrote partial logs under `logs/<run-id>/`. The most informative file is usually `agent.log`. Capture it before retrying, since the next run will create a new directory.

---

## Snapshot for fast re-runs

Once Step 11 has passed end-to-end, snapshot the boot disk. Future VMs from this snapshot skip Steps 2–8 and reach a runnable state in ~2 minutes.

```bash
gcloud compute instances stop mcb-conv-1 --zone=us-central1-a
gcloud compute disks snapshot mcb-conv-1 \
  --zone=us-central1-a \
  --snapshot-names=mcb-conv-baseline
```

To launch a fresh VM from the snapshot:

```bash
gcloud compute disks create mcb-conv-2-disk \
  --zone=us-central1-a \
  --source-snapshot=mcb-conv-baseline \
  --type=pd-balanced --size=100GB

gcloud compute instances create mcb-conv-2 \
  --zone=us-central1-a \
  --machine-type=c3-standard-8 \
  --enable-nested-virtualization \
  --disk=name=mcb-conv-2-disk,boot=yes,auto-delete=yes
```

> The `gcloud` command may warn `Disk size: '100 GB' is larger than image size: '10 GB'`. This is expected — Ubuntu's cloud-init auto-resizes the root partition on first boot.

> The snapshot includes your OpenAI key in `agent/.env`. Treat it as sensitive: store it in a project with restricted IAM, and rotate the key if the snapshot leaves that project.

---

## Tear down

To stop paying for compute (disk costs continue):

```bash
gcloud compute instances stop mcb-conv-1 --zone=us-central1-a
```

To delete everything:

```bash
gcloud compute instances delete mcb-conv-1 --zone=us-central1-a
gcloud compute snapshots delete mcb-conv-baseline   # only if you created one
```

---

## Troubleshooting reference

| Symptom | Likely cause | Fix |
|---|---|---|
| `gcloud compute ssh` hangs | Missing/incorrect SSH firewall rule | Allow TCP/22 from your IP or the IAP range `35.235.240.0/20` |
| `kvm-ok` reports KVM unavailable | VM created without `--enable-nested-virtualization` | Recreate the VM with the flag |
| `permission denied on /var/run/docker.sock` | Docker group change not picked up | Disconnect SSH fully and reconnect |
| `gh release view ... 404` | PAT lacks repo scope or release access | Mint a new PAT with `repo` scope, or set `MOBILECYBENCH_SKIP_GH_CHECK=1` and change `build_type` |
| Emulator boot times out | KVM missing or `/dev/kvm` perms | Re-check Step 2; add user to `kvm` group |
| Model call fails immediately | Bad `OPENAI_API_KEY` or unsupported model | Re-run Check 6; pick a supported model from `agent/custom/model_providers/factory.py` |
| Runner errors `Running emulator(s) detected` | Manual emulator left running | `./stop_emulator.sh` before re-running |
| `cleanup.sh failed with exit code 1` / `Permission denied` removing `config/*` | Previous run left root-owned files (Docker created them) | `sudo rm -rf apps/<app>/config` once, then re-run. Affects any app whose containers write to `config/` (e.g. `home-assistant-android`). The runner pre-cleans **all active backends** at startup, so a stale HA config can block an unrelated app's run. |
| `App '<name>' backend is not on agent_net` | The app's `docker-compose.yml` declares only `shared_net` on its frontend service | Add `agent_net` to the service's `networks:` list and append `agent_net:\n    external: true` to the top-level `networks:` block. Known to affect `openhab` and `termux`. |

For deeper diagnostics, see [`documentation/TROUBLESHOOTING.md`](documentation/TROUBLESHOOTING.md).

---

## Switching providers

**Important:** `gpt-5.5` and other OpenAI models will reject most red-team requests with HTTP 400 / `cyber_policy`:

> *"This content was flagged for possible cybersecurity risk. To get authorized for security work, join the Trusted Access for Cyber program: https://chatgpt.com/cyber"*

In practice the agent runs successfully for ~15–20 turns and then a request crosses the moderation threshold and the run aborts. Unless you have OpenAI Trusted Access for Cyber, use Anthropic or Google instead. To switch:

1. Edit `runner_config.json` and change `model` to one of the supported IDs (e.g. `claude-opus-4-7`, `gemini-3.1-pro`). See `agent/custom/model_providers/factory.py:SupportedModel` for the full list.
2. Ensure the matching variable is in `agent/.env` (`ANTHROPIC_API_KEY` or `GEMINI_API_KEY`). The env var and the model must match — the runner loads exactly one provider key per run.
3. Re-run Check 6 with the appropriate provider's `/v1/models/<model_id>` endpoint to validate the key before launching:
   ```bash
   # Anthropic
   curl -sS https://api.anthropic.com/v1/models/claude-opus-4-7 \
     -H "x-api-key: $ANTHROPIC_API_KEY" -H "anthropic-version: 2023-06-01" \
     | jq -r '.id // .error.message'
   ```
