# MobileCyBench on GKE

Run MobileCyBench experiments in parallel on Google Kubernetes Engine.

## Architecture

Each experiment runs as a K8s Job in a privileged pod with Docker-in-Docker:

```
GKE Node (n2-standard-8, nested virt enabled)
└── Pod (privileged, /dev/kvm hostPath)
    └── Orchestrator container (DinD)
        ├── Android emulator (container or native process)
        ├── Kali agent container
        └── App backend containers
```

## Quick Start

### 1. Create GKE Cluster

```bash
export PROJECT_ID=your-gcp-project
bash infra/gke/setup-cluster.sh
```

### 2. Build & Push Runner Image

```bash
# Build orchestrator base first
docker build -f orchestrator/Dockerfile.orchestrator -t mobilecybench-orchestrator:latest .

# Build GKE runner
docker build -f infra/gke/Dockerfile.runner \
  --build-arg BASE_IMAGE=mobilecybench-orchestrator:latest \
  -t us-central1-docker.pkg.dev/$PROJECT_ID/mobilecybench/runner:latest .

docker push us-central1-docker.pkg.dev/$PROJECT_ID/mobilecybench/runner:latest
```

### 3. Set Model Credentials

The `llm-api-keys` secret is just an environment-variable bag: the Job injects
every key in it into the runner via `envFrom` (see `job-template.yaml`), and the
runner forwards a fixed allowlist on into the agent container
(`AUTH_ENV_PASSTHROUGH` in `agent/runtime/container.py`). The variable names are
not a required schema — **you only provide the credential for the model you
actually run**, not all of them.

```bash
# Example: running an Anthropic model — only ANTHROPIC_API_KEY is needed.
kubectl create secret generic llm-api-keys \
  --namespace=mobilecybench \
  --from-literal=ANTHROPIC_API_KEY=sk-ant-... \
  --dry-run=client -o yaml | kubectl apply -f -
```

Pick the credential that matches your `--models` selection:

- `--models openai/*`    → `OPENAI_API_KEY`
- `--models anthropic/*` → `ANTHROPIC_API_KEY`
- Claude Code via a Pro/Max/Team/Enterprise subscription → **no API key**; run
  `claude setup-token` and set `CLAUDE_CODE_OAUTH_TOKEN` instead.

Add extra keys to the same command only if you use those providers (e.g.
`GEMINI_API_KEY`, `TOGETHER_API_KEY`, or opencode OAuth blobs). For the full,
authoritative list of variables the harness forwards into the agent, see
`agent/.env.example` and `AUTH_ENV_PASSTHROUGH` in
`agent/runtime/container.py`.

Probe-only jobs run a real external agent, so the placeholder values written by
`setup-cluster.sh` must be replaced with a real credential for your model before
submitting jobs or running `test_gke.sh`.

### 4. Submit Probe-Only Redteam Jobs

GKE jobs run an external coding-agent image against active apps from
`apps/app_catalog.json`. Synthetic vulnerability IDs are not used.

```bash
# Single app
python infra/gke/generate_jobs.py \
  --apps conversations \
  --agent-image cybench/mobilecybench:opencode_1.15.6-r1 \
  --models openai/gpt-5.5 \
  --probe-only \
  --attacker-models malicious_app remote_attacker \
  --no-codebase-ablation \
  --agent-wallclock-seconds 1800 \
  --image us-central1-docker.pkg.dev/$PROJECT_ID/mobilecybench/runner:latest \
  --gcs-bucket $PROJECT_ID-mobilecybench-results \
  --apply

# All active apps
python infra/gke/generate_jobs.py \
  --all \
  --agent-image cybench/mobilecybench:opencode_1.15.6-r1 \
  --models openai/gpt-5.5 \
  --probe-only \
  --attacker-models malicious_app remote_attacker \
  --no-codebase-ablation \
  --agent-wallclock-seconds 1800 \
  --image us-central1-docker.pkg.dev/$PROJECT_ID/mobilecybench/runner:latest \
  --gcs-bucket $PROJECT_ID-mobilecybench-results \
  --apply
```

`--no-codebase-ablation` renders both legs (source mounted vs. APK-only). The
`--image` flag is still the GKE **runner** pod image; `--agent-image` is a
separate value forwarded into `runner_config.agent_image`. Pass `--models`
when the agent image expects a specific provider/model string; the opencode
image examples above use `openai/gpt-5.5`. Probe-only jobs cannot be combined
with `--dry-run` or `--gold-run`: dry-run skips scoring, and gold-run requires
a task bundle/reference exploit.

### 5. Monitor

```bash
# Watch jobs
kubectl get jobs -n mobilecybench --watch

# Check specific job logs
kubectl logs -n mobilecybench job/mcb-conversations-malicious-app-src-openai-gpt-5-5 -f

# See pod status
kubectl get pods -n mobilecybench
```

### 6. Collect Results

```bash
python infra/gke/collect_results.py \
  --bucket $PROJECT_ID-mobilecybench-results \
  --csv results.csv
```

## Emulator Modes

Set via `EMULATOR_BACKEND` env var (default: `container`):

- **`container`** (recommended for GKE): Emulator runs as a Docker container inside DinD. Requires `/dev/kvm` passthrough through 3 levels (node → pod → DinD → emulator container).
- **`native`**: Emulator runs as a native process inside the orchestrator. Fallback if nested container KVM passthrough fails.

For headless GPU flakes, generate jobs with `--emulator-gpu swangle` or set
`MOBILECYBENCH_EMULATOR_GPU=swangle` before running `generate_jobs.py`. Empty
keeps the runner default (`swiftshader`).

## GKE Cluster Details

- **Machine type**: `n2-standard-8` (8 vCPU, 32GB RAM), supports nested virtualization
- **Node image**: `UBUNTU_CONTAINERD` (required for `/dev/kvm`)
- **Autoscaling**: 0–20 nodes, ~3 experiments per node
- **Spot instances**: ~60-70% cost savings
- **Resource quota**: Max 60 pods in the mobilecybench namespace

## Files

| File | Purpose |
|------|---------|
| `Dockerfile.runner` | Extends orchestrator image + gcloud CLI |
| `entrypoint-gke.sh` | DinD startup + run experiment + GCS upload |
| `build_runner_config.sh` | Layer Job env-var overrides onto the base runner config |
| `job-template.yaml` | Reference K8s Job spec |
| `namespace.yaml` | Namespace + ResourceQuota |
| `setup-cluster.sh` | GKE + Artifact Registry + GCS setup |
| `generate_jobs.py` | Generate/apply K8s Job YAMLs for experiment matrix |
| `collect_results.py` | Download + aggregate results from GCS |

## Troubleshooting

### KVM not available in pod
Verify nested virtualization is enabled on the node:
```bash
kubectl run kvm-test --rm -it --image=ubuntu --privileged -- ls -la /dev/kvm
```

### Emulator container fails to start
Check if DinD can access KVM:
```bash
# Exec into the pod
kubectl exec -it -n mobilecybench <pod-name> -- bash
# Inside the pod:
docker run --rm --device /dev/kvm ubuntu ls -la /dev/kvm
```

### Jobs stuck in Pending
Check node autoscaler status and resource quota:
```bash
kubectl describe nodes
kubectl describe resourcequota -n mobilecybench
```
