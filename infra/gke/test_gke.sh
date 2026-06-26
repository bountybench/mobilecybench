#!/bin/bash
# End-to-end GKE infrastructure test — deploys a real redteam probe-only K8s Job
# and validates the full GKE pipeline:
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
#   bash infra/gke/test_gke.sh --emulator-backend native    # test fallback mode
#   bash infra/gke/test_gke.sh --no-cleanup               # keep pod for debugging

set -euo pipefail

APP_NAME="moememos"
EMULATOR_BACKEND="container"
CLEANUP=true
NAMESPACE="mobilecybench"
IMAGE="${RUNNER_IMAGE:-}"
GCS_BUCKET="${GCS_BUCKET:-}"
DRY_RUN="false"
GOLD_RUN="false"
AGENT_IMAGE="${AGENT_IMAGE:-cybench/mobilecybench:opencode_1.15.6-r1}"
MODEL="${MODEL:-openai/gpt-5.5}"
ATTACKER_MODEL="${ATTACKER_MODEL:-remote_attacker}"
AGENT_WALLCLOCK_SECONDS="${AGENT_WALLCLOCK_SECONDS:-1800}"
ACTIVE_DEADLINE_SECONDS="${ACTIVE_DEADLINE_SECONDS:-$((AGENT_WALLCLOCK_SECONDS + 900))}"

while [[ $# -gt 0 ]]; do
    case $1 in
        --app) APP_NAME="$2"; shift 2 ;;
        --emulator-backend) EMULATOR_BACKEND="$2"; shift 2 ;;
        --image) IMAGE="$2"; shift 2 ;;
        --agent-image) AGENT_IMAGE="$2"; shift 2 ;;
        --model) MODEL="$2"; shift 2 ;;
        --attacker-model) ATTACKER_MODEL="$2"; shift 2 ;;
        --no-cleanup) CLEANUP=false; shift ;;
        --dry-run) echo "ERROR: --dry-run is incompatible with redteam probe-only smoke"; exit 1 ;;
        --gold-run) echo "ERROR: --gold-run is incompatible with redteam probe-only smoke"; exit 1 ;;
        --no-dry-run) DRY_RUN="false"; shift ;;
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
echo "Emulator backend: $EMULATOR_BACKEND"
echo "Image:          $IMAGE"
echo "Namespace:      $NAMESPACE"
echo "GCS bucket:     ${GCS_BUCKET:-<none>}"
echo "Dry run:        $DRY_RUN"
echo "Gold run:       $GOLD_RUN"
echo "Agent image:    $AGENT_IMAGE"
echo "Model:          $MODEL"
echo "Attacker model: $ATTACKER_MODEL"
echo "Agent wallclock: $AGENT_WALLCLOCK_SECONDS"
echo "Pod deadline:   $ACTIVE_DEADLINE_SECONDS"
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
    echo "ERROR: Secret 'llm-api-keys' not found."
    echo "Probe-only GKE smoke runs a real external agent; create the secret with real provider credentials first."
    exit 1
fi
if [[ "$MODEL" == openai/* ]]; then
    OPENAI_KEY_B64=$(kubectl get secret llm-api-keys -n "$NAMESPACE" -o jsonpath='{.data.OPENAI_API_KEY}' 2>/dev/null || true)
    PLACEHOLDER_B64=$(printf 'placeholder' | base64 | tr -d '\n')
    TEST_PLACEHOLDER_B64=$(printf 'test-placeholder' | base64 | tr -d '\n')
    if [ -z "$OPENAI_KEY_B64" ] || \
       [ "$OPENAI_KEY_B64" = "$PLACEHOLDER_B64" ] || \
       [ "$OPENAI_KEY_B64" = "$TEST_PLACEHOLDER_B64" ]; then
        echo "ERROR: llm-api-keys.OPENAI_API_KEY is missing or still a placeholder for MODEL=$MODEL."
        exit 1
    fi
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
  activeDeadlineSeconds: $ACTIVE_DEADLINE_SECONDS
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
              value: "$MODEL"
            - name: EMULATOR_BACKEND
              value: "$EMULATOR_BACKEND"
            - name: DRY_RUN
              value: "$DRY_RUN"
            - name: GOLD_RUN
              value: "$GOLD_RUN"
            - name: AGENT_IMAGE
              value: "$AGENT_IMAGE"
            - name: AGENT_MODE
              value: "external"
            - name: WORKFLOW
              value: "redteam"
            - name: PROBE_ONLY
              value: "true"
            - name: ATTACKER_MODEL
              value: "$ATTACKER_MODEL"
            - name: NO_CODEBASE
              value: "false"
            - name: AGENT_WALLCLOCK_SECONDS
              value: "$AGENT_WALLCLOCK_SECONDS"
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
            - name: docker-storage
              mountPath: /var/lib/docker
      volumes:
        - name: dev-kvm
          hostPath:
            path: /dev/kvm
            type: CharDevice
        - name: docker-storage
          emptyDir: {}
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
