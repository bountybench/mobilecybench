# MobileCyBench on GKE

Run MobileCyBench experiments in parallel on Google Kubernetes Engine.

## Architecture

Each experiment runs as a K8s Job in a privileged pod with Docker-in-Docker:

```
GKE Node (n2d-standard-8, nested virt enabled)
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

### 4. Submit Experiments

```bash
# Single experiment
python infra/gke/generate_jobs.py \
  --apps moememos \
  --models gpt-4o \
  --image us-central1-docker.pkg.dev/$PROJECT_ID/mobilecybench/runner:latest \
  --gcs-bucket $PROJECT_ID-mobilecybench-results \
  --apply

# Full matrix
python infra/gke/generate_jobs.py \
  --all \
  --models gpt-4o claude-sonnet-4-5-20250929 \
  --image us-central1-docker.pkg.dev/$PROJECT_ID/mobilecybench/runner:latest \
  --gcs-bucket $PROJECT_ID-mobilecybench-results \
  --apply
```

### 5. Monitor

```bash
# Watch jobs
kubectl get jobs -n mobilecybench --watch

# Check specific job logs
kubectl logs -n mobilecybench job/mcb-moememos-vuln-0-gpt-4o -f

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

Set via `EMULATOR_MODE` env var (default: `container`):

- **`container`** (recommended for GKE): Emulator runs as a Docker container inside DinD. Requires `/dev/kvm` passthrough through 3 levels (node → pod → DinD → emulator container).
- **`native`**: Emulator runs as a native process inside the orchestrator. Fallback if nested container KVM passthrough fails.

## GKE Cluster Details

- **Machine type**: `n2d-standard-8` (8 vCPU, 32GB RAM) — AMD, supports nested virtualization
- **Node image**: `UBUNTU_CONTAINERD` (required for `/dev/kvm`)
- **Autoscaling**: 0–20 nodes, ~3 experiments per node
- **Spot instances**: ~60-70% cost savings
- **Resource quota**: Max 60 pods in the mobilecybench namespace

## Files

| File | Purpose |
|------|---------|
| `Dockerfile.runner` | Extends orchestrator image + gcloud CLI |
| `entrypoint-gke.sh` | DinD startup + run experiment + GCS upload |
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
