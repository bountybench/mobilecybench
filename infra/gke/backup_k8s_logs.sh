#!/bin/bash
set -euo pipefail

NAMESPACE="${NAMESPACE:-mobilecybench}"
BACKUP_DIR="${1:-gke-log-backups/$(date +%Y%m%d-%H%M%S)}"
GCS_BACKUP_URI="${GCS_BACKUP_URI:-}"
LOGS_ROOT="${LOGS_ROOT:-/mobilecybench/logs}"

mkdir -p "$BACKUP_DIR"

echo "Writing Kubernetes backup to $BACKUP_DIR"

kubectl get jobs -n "$NAMESPACE" -o yaml > "$BACKUP_DIR/jobs.yaml"
kubectl get pods -n "$NAMESPACE" -o yaml > "$BACKUP_DIR/pods.yaml"
kubectl get events -n "$NAMESPACE" --sort-by=.lastTimestamp > "$BACKUP_DIR/events.txt" || true

kubectl get jobs -n "$NAMESPACE" -o name | while read -r job; do
    name="${job#job.batch/}"
    kubectl describe -n "$NAMESPACE" "$job" > "$BACKUP_DIR/${name}.job.describe.txt" 2>&1 || true
done

kubectl get pods -n "$NAMESPACE" -o name | while read -r pod; do
    name="${pod#pod/}"
    pod_dir="$BACKUP_DIR/$name"
    mkdir -p "$pod_dir"

    kubectl get -n "$NAMESPACE" "$pod" -o yaml > "$pod_dir/pod.yaml" 2>&1 || true
    kubectl describe -n "$NAMESPACE" "$pod" > "$pod_dir/pod.describe.txt" 2>&1 || true
    kubectl logs -n "$NAMESPACE" "$name" --all-containers=true \
        > "$pod_dir/pod.log" 2>&1 || true
    kubectl logs -n "$NAMESPACE" "$name" --all-containers=true --previous \
        > "$pod_dir/pod.previous.log" 2>&1 || true

    bundle_src="$LOGS_ROOT/gke_failure/$name/upload_failure_bundle.tar.gz"
    manifest_src="$LOGS_ROOT/gke_failure/$name/manual_retrieval.txt"
    preflight_src="$LOGS_ROOT/gke/gcs_auth_preflight.txt"

    kubectl cp \
        "${NAMESPACE}/${name}:${bundle_src}" \
        "$pod_dir/upload_failure_bundle.tar.gz" >/dev/null 2>&1 || true
    kubectl cp \
        "${NAMESPACE}/${name}:${manifest_src}" \
        "$pod_dir/manual_retrieval.txt" >/dev/null 2>&1 || true
    kubectl cp \
        "${NAMESPACE}/${name}:${preflight_src}" \
        "$pod_dir/gcs_auth_preflight.txt" >/dev/null 2>&1 || true
done

if [ -n "$GCS_BACKUP_URI" ]; then
    echo "Uploading backup to $GCS_BACKUP_URI"
    gcloud storage cp -r "$BACKUP_DIR" "$GCS_BACKUP_URI"
fi

echo "Backup complete: $BACKUP_DIR"
