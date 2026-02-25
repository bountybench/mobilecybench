#!/bin/bash
# End-to-end GKE infrastructure test — deploys a real K8s Job in dry_run mode.
# No LLM calls, but validates the full GKE pipeline:
#
#   1. Pod scheduling on a KVM-capable node
#   2. /dev/kvm hostPath passthrough
#   3. Privileged DinD inside the pod
#   4. Container emulator mode (Docker-in-Docker-in-K8s)
#   5. Emulator boot + ADB connectivity
#   6. Secret mounting (llm-api-keys)
#   7. GCS result upload
#   8. Pod completion + cleanup
#
# Prerequisites:
#   - GKE cluster created (setup-cluster.sh)
#   - Runner image pushed to Artifact Registry
#   - kubectl configured for the cluster
#
# Usage:
#   bash infra/gke/test_gke.sh
#   bash infra/gke/test_gke.sh --app moememos
#   bash infra/gke/test_gke.sh --emulator-mode native    # test fallback mode
#   bash infra/gke/test_gke.sh --gold-run                 # run gold exploit + evaluation
#   bash infra/gke/test_gke.sh --no-cleanup               # keep pod for debugging

set -euo pipefail

APP_NAME="moememos"
EMULATOR_MODE="container"
CLEANUP=true
GOLD_RUN=false
NAMESPACE="mobilecybench"
IMAGE="${RUNNER_IMAGE:-}"
GCS_BUCKET="${GCS_BUCKET:-}"

while [[ $# -gt 0 ]]; do
    case $1 in
        --app) APP_NAME="$2"; shift 2 ;;
        --emulator-mode) EMULATOR_MODE="$2"; shift 2 ;;
        --image) IMAGE="$2"; shift 2 ;;
        --no-cleanup) CLEANUP=false; shift ;;
        --gold-run) GOLD_RUN=true; shift ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

if [ -z "$IMAGE" ]; then
    echo "ERROR: Set RUNNER_IMAGE env var or pass --image <uri>"
    echo "  e.g., us-central1-docker.pkg.dev/PROJECT_ID/mobilecybench/runner:latest"
    exit 1
fi

JOB_NAME="mcb-test-$(date +%s)"

echo "=== GKE Infrastructure Test ==="
echo "Job:            $JOB_NAME"
echo "App:            $APP_NAME"
echo "Emulator mode:  $EMULATOR_MODE"
echo "Gold run:       $GOLD_RUN"
echo "Image:          $IMAGE"
echo "Namespace:      $NAMESPACE"
echo "GCS bucket:     ${GCS_BUCKET:-<none>}"
echo "Cleanup:        $CLEANUP"
echo ""

# ─── Preflight checks ──────────────────────────────────────────────────────
echo "--- Preflight checks ---"

if ! kubectl get namespace "$NAMESPACE" >/dev/null 2>&1; then
    echo "ERROR: Namespace '$NAMESPACE' not found. Run setup-cluster.sh first."
    exit 1
fi

echo "Checking for KVM-capable nodes..."
KVM_NODES=$(kubectl get nodes -o json | \
    python3 -c "
import json, sys
nodes = json.load(sys.stdin)['items']
for n in nodes:
    name = n['metadata']['name']
    # Nodes with nested virt have /dev/kvm
    print(f'  {name}')
" 2>/dev/null || echo "  (could not enumerate)")
echo "$KVM_NODES"

echo "Checking secret 'llm-api-keys'..."
if kubectl get secret llm-api-keys -n "$NAMESPACE" >/dev/null 2>&1; then
    echo "  Secret found"
else
    echo "  WARNING: Secret not found — creating placeholder"
    kubectl create secret generic llm-api-keys \
        --namespace="$NAMESPACE" \
        --from-literal=OPENAI_API_KEY=test-placeholder \
        --dry-run=client -o yaml | kubectl apply -f -
fi
echo ""

# ─── Deploy test Job ───────────────────────────────────────────────────────
echo "--- Deploying test Job: $JOB_NAME ---"

kubectl apply -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: $JOB_NAME
  namespace: $NAMESPACE
  labels:
    app: mobilecybench
    test: "true"
spec:
  backoffLimit: 0
  ttlSecondsAfterFinished: 3600
  activeDeadlineSeconds: 1800
  template:
    metadata:
      labels:
        app: mobilecybench
        test: "true"
    spec:
      restartPolicy: Never
      containers:
        - name: runner
          image: $IMAGE
          securityContext:
            privileged: true
          resources:
            requests:
              cpu: "2"
              memory: "8Gi"
            limits:
              cpu: "4"
              memory: "16Gi"
          env:
            - name: APP_NAME
              value: "$APP_NAME"
            - name: MODEL
              value: "notarealmodel"
            - name: VULN_ID
              value: "vuln_0"
            - name: EMULATOR_MODE
              value: "$EMULATOR_MODE"
            - name: DRY_RUN
              value: "$([ "$GOLD_RUN" = true ] && echo false || echo true)"
            - name: GOLD_RUN
              value: "$GOLD_RUN"
            - name: GCS_BUCKET
              value: "$GCS_BUCKET"
            - name: RUN_ID
              value: "$JOB_NAME"
          envFrom:
            - secretRef:
                name: llm-api-keys
          volumeMounts:
            - name: dev-kvm
              mountPath: /dev/kvm
      volumes:
        - name: dev-kvm
          hostPath:
            path: /dev/kvm
            type: CharDevice
EOF

echo "Job submitted."
echo ""

# ─── Wait for pod to start ─────────────────────────────────────────────────
echo "--- Waiting for pod to start (timeout: 5m) ---"
POD_NAME=""
for i in $(seq 1 60); do
    POD_NAME=$(kubectl get pods -n "$NAMESPACE" -l "job-name=$JOB_NAME" \
        -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
    if [ -n "$POD_NAME" ]; then
        PHASE=$(kubectl get pod "$POD_NAME" -n "$NAMESPACE" \
            -o jsonpath='{.status.phase}' 2>/dev/null || true)
        if [ "$PHASE" = "Running" ] || [ "$PHASE" = "Succeeded" ] || [ "$PHASE" = "Failed" ]; then
            echo "Pod: $POD_NAME (phase: $PHASE)"
            break
        fi
        echo "  Pod $POD_NAME phase: $PHASE"
    else
        echo "  Waiting for pod creation..."
    fi
    sleep 5
done

if [ -z "$POD_NAME" ]; then
    echo "ERROR: Pod never created. Check:"
    echo "  kubectl describe job $JOB_NAME -n $NAMESPACE"
    echo "  kubectl get events -n $NAMESPACE --sort-by=.lastTimestamp"
    exit 1
fi

echo ""

# ─── Stream logs ───────────────────────────────────────────────────────────
echo "--- Streaming pod logs (Ctrl+C to stop following, job continues) ---"
echo ""
kubectl logs -f "$POD_NAME" -n "$NAMESPACE" || true

echo ""

# ─── Check result ──────────────────────────────────────────────────────────
echo "--- Job result ---"
JOB_STATUS=$(kubectl get job "$JOB_NAME" -n "$NAMESPACE" \
    -o jsonpath='{.status.conditions[0].type}' 2>/dev/null || echo "Unknown")
echo "Job status: $JOB_STATUS"

POD_EXIT=$(kubectl get pod "$POD_NAME" -n "$NAMESPACE" \
    -o jsonpath='{.status.containerStatuses[0].state.terminated.exitCode}' 2>/dev/null || echo "?")
echo "Pod exit code: $POD_EXIT"

# ─── KVM check ─────────────────────────────────────────────────────────────
echo ""
echo "--- Diagnostic: checking KVM inside pod ---"
kubectl exec "$POD_NAME" -n "$NAMESPACE" -- ls -la /dev/kvm 2>/dev/null || \
    echo "  (pod already terminated — check logs above for KVM status)"

# ─── Cleanup ───────────────────────────────────────────────────────────────
if [ "$CLEANUP" = true ]; then
    echo ""
    echo "--- Cleaning up ---"
    kubectl delete job "$JOB_NAME" -n "$NAMESPACE" --ignore-not-found
    echo "Job deleted."
else
    echo ""
    echo "--- Skipping cleanup (--no-cleanup) ---"
    echo "Debug with:"
    echo "  kubectl exec -it $POD_NAME -n $NAMESPACE -- bash"
    echo "  kubectl logs $POD_NAME -n $NAMESPACE"
    echo "  kubectl delete job $JOB_NAME -n $NAMESPACE"
fi

echo ""
if [ "$POD_EXIT" = "0" ]; then
    echo "=== TEST PASSED ==="
else
    echo "=== TEST FAILED (exit code: $POD_EXIT) ==="
    echo ""
    echo "Troubleshooting:"
    echo "  kubectl describe pod $POD_NAME -n $NAMESPACE"
    echo "  kubectl logs $POD_NAME -n $NAMESPACE"
    exit 1
fi
