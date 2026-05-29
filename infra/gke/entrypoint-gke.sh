#!/bin/bash
set -e

# ─── GCS auth fallback ──────────────────────────────────────────────────────
# When Workload Identity isn't usable (e.g. Stanford org policy blocks
# iam.serviceAccounts.setIamPolicy), we mount a SA key as a secret at
# /etc/gcp-sa/key.json. Activate it for gcloud + gsutil so the final
# GCS upload works. Skipped silently if the key file isn't mounted.
if [ -n "${GOOGLE_APPLICATION_CREDENTIALS:-}" ] && [ -f "${GOOGLE_APPLICATION_CREDENTIALS}" ]; then
    echo "Activating SA key for GCS auth: ${GOOGLE_APPLICATION_CREDENTIALS}"
    gcloud auth activate-service-account --key-file="${GOOGLE_APPLICATION_CREDENTIALS}" \
        --quiet 2>&1 | tail -2 || echo "WARNING: SA key activation failed (continuing)"
fi

# ─── DinD setup (same as orchestrator/entrypoint.sh) ───────────────────────
rm -f /var/run/docker.pid
# Use explicit DNS servers to prevent the Android emulator's virtual DNS
# (10.0.2.3) from polluting the DinD daemon's resolver. Without this,
# image pulls and builds fail after the emulator container starts.
dockerd --host=unix:///var/run/docker.sock --dns 8.8.8.8 --dns 8.8.4.4 &

echo "Waiting for Docker daemon to start..."
timeout=30
while [ $timeout -gt 0 ]; do
    if docker info >/dev/null 2>&1; then
        echo "Docker daemon is ready"
        break
    fi
    sleep 1
    timeout=$((timeout - 1))
done

if [ $timeout -eq 0 ]; then
    echo "Docker daemon failed to start"
    exit 1
fi

docker network create shared_net || true
docker network create --internal agent_net || true

# Docker Hub auth (optional — avoids rate limits on image pulls)
if [ -n "${DOCKERHUB_USERNAME:-}" ] && [ "${DOCKERHUB_USERNAME}" != "placeholder" ] && [ -n "${DOCKERHUB_TOKEN:-}" ]; then
    echo "$DOCKERHUB_TOKEN" | docker login -u "$DOCKERHUB_USERNAME" --password-stdin || \
        echo "WARNING: Docker Hub login failed (continuing without auth)"
fi

# ─── Pre-pull emulator image ─────────────────────────────────────────────
# The Python Docker SDK has a 60s default timeout on containers.run(), which
# is not enough for pulling the ~10 GB emulator image. Pre-pulling here
# avoids that timeout.
EMULATOR_IMAGE="${EMULATOR_IMAGE:-cybench/mobilecybench-emulator:latest}"
if [ "${EMULATOR_BACKEND:-container}" = "container" ]; then
    echo "Pre-pulling emulator image: $EMULATOR_IMAGE"
    docker pull "$EMULATOR_IMAGE"
    echo "Emulator image ready"
fi

# Install package if needed (in case image was built without -e install)
if [ -f /mobilecybench/pyproject.toml ]; then
    cd /mobilecybench && pip install --no-cache-dir -e . >/dev/null 2>&1 || true
fi

# Start ADB server (listen on all interfaces for kali container access)
adb -a start-server

# ─── Build runner config with GKE overrides ─────────────────────────────────
# Override logic lives in build_runner_config.sh so it can be unit-tested
# without a full DinD/emulator boot.
CONFIG_SRC="/mobilecybench/runner_config.json"
CONFIG_DST="/tmp/runner_config.json"

bash /mobilecybench/infra/gke/build_runner_config.sh "$CONFIG_SRC" "$CONFIG_DST"

echo "Runner config:"
cat "$CONFIG_DST"

# ─── Run experiment ─────────────────────────────────────────────────────────
# Set logs dir so GCS upload can find experiment results
export MOBILECYBENCH_LOGS_DIR="${MOBILECYBENCH_LOGS_DIR:-/mobilecybench/logs}"

cd /mobilecybench
set +e
python3 runner.py "$APP_NAME" --config "$CONFIG_DST"
EXIT_CODE=$?
set -e

# ─── Upload results to GCS ──────────────────────────────────────────────────
if [ -n "$GCS_BUCKET" ] && [ -n "$MOBILECYBENCH_LOGS_DIR" ]; then
    RUN_ID="${RUN_ID:-$(date +%s)}"
    # Build the object prefix from non-empty segments only — VULN_ID (and
    # sometimes MODEL) are empty in probe-only mode and would otherwise
    # produce empty "//" path components.
    path_segs=("$APP_NAME")
    [ -n "${VULN_ID:-}" ] && path_segs+=("$VULN_ID")
    [ -n "${MODEL:-}" ] && path_segs+=("$MODEL")
    path_segs+=("$RUN_ID")
    GCS_PATH="gs://$GCS_BUCKET/$(IFS=/; echo "${path_segs[*]}")/"
    echo "Uploading results to $GCS_PATH"
    # Identify run dirs by the presence of run_summary.json (content-based,
    # decoupled from the runner's directory-naming convention so the name
    # can change without touching the GKE pipeline). Covers both real runs
    # (logs/<run>/) and gold runs (logs/gold/<run>_gold/).
    dirs=()
    while IFS= read -r summary; do
        dirs+=("$(dirname "$summary")")
    done < <(find "$MOBILECYBENCH_LOGS_DIR" -maxdepth 3 -name run_summary.json -type f 2>/dev/null)
    if [ ${#dirs[@]} -gt 0 ]; then
        gsutil -m cp -r "${dirs[@]}" "$GCS_PATH" || echo "WARNING: GCS upload failed"
    else
        echo "WARNING: no experiment logs found to upload"
    fi
fi

exit $EXIT_CODE
