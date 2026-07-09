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

### 3. Set API Keys

```bash
kubectl create secret generic llm-api-keys \
  --namespace=mobilecybench \
  --from-literal=OPENAI_API_KEY=sk-... \
  --from-literal=ANTHROPIC_API_KEY=sk-ant-... \
  --dry-run=client -o yaml | kubectl apply -f -
```

Probe-only jobs run a real external agent, so placeholder keys from cluster
setup must be replaced before submitting jobs or running `test_gke.sh`.

### 4. Submit the full grid

The GKE equivalent of `python runner.py --config runner_config_batch.json` — but
fanned out across the cluster instead of run sequentially. **The defaults are the
full grid** (probe-only redteam, both attacker models, both visibility legs), so
you only pass the agent image + model and the runner image + bucket:

```bash
export PROJECT_ID=your-gcp-project
export RUNNER_IMAGE=us-central1-docker.pkg.dev/$PROJECT_ID/mobilecybench/runner:latest
export GCS_BUCKET=$PROJECT_ID-mobilecybench-results

python infra/gke/generate_jobs.py --all \
  --agent-image cybench/mobilecybench:claudecode_2.1.170-r1 \
  --models claude-opus-4-8 \
  --apply
```

That renders **13 apps × 2 attacker models × 2 visibility legs = 52 Jobs** and
applies them. Each cell's `network_mode` + `apk_obfuscation` are set to match the
visibility leg automatically (source → `permissive`/off, apk-only →
`restricted`/on), so the grid matches the sequential batch runner.

**Pick the agent image for the CLI you want** (published on Docker Hub, pulled
automatically by the pods):

| Agent CLI | `--agent-image` | `--models` example |
|-----------|-----------------|--------------------|
| Claude Code | `cybench/mobilecybench:claudecode_2.1.170-r1` | `claude-opus-4-8` (any Anthropic id) |
| opencode | `cybench/mobilecybench:opencode_1.15.6-r1` | `openai/gpt-5.5` (`provider/model`) |
| codex | `cybench/mobilecybench:codex_0.130.0-r2` | `gpt-5.5` (OpenAI id) |

`--agent-image` and `--models` are **required and coupled** — the agent CLI and
its model string go together, so there is no default (a claudecode image needs an
Anthropic model, opencode needs `provider/model`, etc.).

**Narrow it** for a quick smoke run by adding flags:

```bash
# one app, one visibility leg, one attacker model
python infra/gke/generate_jobs.py --apps conversations \
  --agent-image cybench/mobilecybench:claudecode_2.1.170-r1 --models claude-opus-4-8 \
  --visibility source --attacker-models malicious_app \
  --apply
```

- `--visibility {both,source,apk_only}` (default `both`) picks the leg(s);
  `--no-codebase-ablation` is a deprecated alias for `--visibility both`.
- `--image` is the GKE **runner** pod image (defaults from `$RUNNER_IMAGE`);
  `--agent-image` is separate, forwarded into `runner_config.agent_image`.
- Probe-only is the only supported mode; `--no-probe-only`, `--dry-run`, and
  `--gold-run` are rejected.

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
