#!/bin/bash
# Setup GKE cluster, Artifact Registry, and GCS bucket for MobileCyBench.
#
# Prerequisites:
#   - gcloud CLI authenticated with a project that has GKE, AR, and GCS APIs enabled
#   - kubectl configured
#
# Usage:
#   bash infra/gke/setup-cluster.sh

set -euo pipefail

PROJECT_ID="${PROJECT_ID:?Set PROJECT_ID env var}"
REGION="${REGION:-us-central1}"
ZONE="${ZONE:-us-central1-a}"
CLUSTER_NAME="${CLUSTER_NAME:-mobilecybench}"
GCS_BUCKET="${GCS_BUCKET:-${PROJECT_ID}-mobilecybench-results}"
AR_REPO="${AR_REPO:-mobilecybench}"

echo "=== MobileCyBench GKE Setup ==="
echo "Project:  $PROJECT_ID"
echo "Region:   $REGION"
echo "Zone:     $ZONE"
echo "Cluster:  $CLUSTER_NAME"
echo ""

# ─── 1. Artifact Registry ──────────────────────────────────────────────────
echo "--- Creating Artifact Registry repository ---"
gcloud artifacts repositories create "$AR_REPO" \
  --repository-format=docker \
  --location="$REGION" \
  --project="$PROJECT_ID" \
  2>/dev/null || echo "Repository already exists"

echo "--- Configuring Docker auth for AR ---"
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

# ─── 2. GCS bucket for results ─────────────────────────────────────────────
echo "--- Creating GCS bucket ---"
gsutil mb -p "$PROJECT_ID" -l "$REGION" "gs://$GCS_BUCKET" 2>/dev/null || \
  echo "Bucket already exists"

# ─── 3. GKE cluster ────────────────────────────────────────────────────────
echo "--- Creating GKE cluster ---"
gcloud container clusters create "$CLUSTER_NAME" \
  --project="$PROJECT_ID" \
  --zone="$ZONE" \
  --machine-type=n2-standard-8 \
  --image-type=UBUNTU_CONTAINERD \
  --num-nodes=1 \
  --enable-autoscaling --min-nodes=0 --max-nodes=20 \
  --spot \
  --disk-size=100 --disk-type=pd-ssd \
  --enable-nested-virtualization \
  --workload-pool="${PROJECT_ID}.svc.id.goog"

echo "--- Getting cluster credentials ---"
gcloud container clusters get-credentials "$CLUSTER_NAME" \
  --zone="$ZONE" --project="$PROJECT_ID"

# ─── 4. Namespace + quota ──────────────────────────────────────────────────
echo "--- Applying namespace and quota ---"
kubectl apply -f "$(dirname "$0")/namespace.yaml"

# ─── 5. Create secret placeholder ──────────────────────────────────────────
echo "--- Creating LLM API keys secret (placeholder) ---"
kubectl create secret generic llm-api-keys \
  --namespace=mobilecybench \
  --from-literal=OPENAI_API_KEY="${OPENAI_API_KEY:-placeholder}" \
  --from-literal=ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-placeholder}" \
  --dry-run=client -o yaml | kubectl apply -f -

# ─── 6. Image cache DaemonSet ─────────────────────────────────────────────
echo "--- Deploying image-cache DaemonSet ---"
kubectl apply -f "$(dirname "$0")/daemonset-image-cache.yaml"
echo "  DaemonSet will start caching emulator + agent images on each node."
echo "  Monitor with: kubectl logs -n mobilecybench -l app=image-cache -f"

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Build and push the runner image:"
echo "     docker build -f infra/gke/Dockerfile.runner \\"
echo "       --build-arg BASE_IMAGE=mobilecybench-orchestrator:latest \\"
echo "       -t ${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/runner:latest ."
echo "     docker push ${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/runner:latest"
echo ""
echo "  2. Update the secret with real API keys:"
echo "     kubectl create secret generic llm-api-keys \\"
echo "       --namespace=mobilecybench \\"
echo "       --from-literal=OPENAI_API_KEY=sk-... \\"
echo "       --from-literal=ANTHROPIC_API_KEY=sk-ant-... \\"
echo "       --dry-run=client -o yaml | kubectl apply -f -"
echo ""
echo "  3. Generate and submit jobs:"
echo "     python infra/gke/generate_jobs.py --apps moememos --models gpt-4o --apply"
