#!/bin/bash
set -e

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

# Optional preloaded inner-Docker images. This lets specialized runner images
# carry private BYO agent images without requiring DinD registry auth at runtime.
PRELOADED_AGENT_IMAGE_DIR="${PRELOADED_AGENT_IMAGE_DIR:-/mobilecybench/preloaded-agent-images}"
if [ -d "$PRELOADED_AGENT_IMAGE_DIR" ]; then
    shopt -s nullglob
    for image_tar in "$PRELOADED_AGENT_IMAGE_DIR"/*.tar "$PRELOADED_AGENT_IMAGE_DIR"/*.tar.gz; do
        echo "Loading preloaded Docker image: $image_tar"
        docker load -i "$image_tar"
    done
    shopt -u nullglob
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
upload_failed=0
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
        if ! gsutil -m cp -r "${dirs[@]}" "$GCS_PATH"; then
            echo "WARNING: GCS upload failed"
            upload_failed=1
        fi
    else
        echo "WARNING: no experiment logs found to upload"
        upload_failed=1
    fi
fi

if [ "$upload_failed" -ne 0 ]; then
    RUN_ID="${RUN_ID:-$(date +%s)}"
    failure_dir="$MOBILECYBENCH_LOGS_DIR/gke_failure/$RUN_ID"
    mkdir -p "$failure_dir"
    cp "$CONFIG_DST" "$failure_dir/runner_config.json" 2>/dev/null || true
    env | sort > "$failure_dir/gke_env.txt" 2>/dev/null || true
    find "$MOBILECYBENCH_LOGS_DIR" -maxdepth 4 -type f > "$failure_dir/log_files.txt" 2>/dev/null || true

    bundle="$failure_dir/upload_failure_bundle.tar.gz"
    tar -C "$MOBILECYBENCH_LOGS_DIR" \
        --exclude="./gke_failure/$RUN_ID/upload_failure_bundle.tar.gz" \
        -czf "$bundle" . || true
    echo "Preserved manual-retrieval bundle at $bundle"
    echo "Retrieve with:"
    echo "  kubectl cp mobilecybench/$RUN_ID:$bundle ./upload_failure_bundle.tar.gz"

    hold_seconds="${UPLOAD_FAILURE_HOLD_SECONDS:-0}"
    if [ "$hold_seconds" -gt 0 ] 2>/dev/null; then
        echo "Holding container for ${hold_seconds}s so artifacts can be copied manually."
        sleep "$hold_seconds"
    fi
fi

exit $EXIT_CODE
