#!/bin/bash
set -e

# ─── Copy baked Docker data into per-pod emptyDir ────────────────────────
# The job template mounts emptyDir at /var/lib/docker for per-pod isolation.
# The baked images live at /var/lib/docker-baked in the image layer.
# cp -a is faster than docker pull (~1-2 min vs ~6-7 min) because it's
# simple file copy — no decompression or database rebuilding.
BAKED_DIR="/var/lib/docker-baked"
SKIP_IMAGE_LOAD=false

if [ -d "$BAKED_DIR" ] && [ "$(ls -A $BAKED_DIR 2>/dev/null)" ]; then
    echo "Copying baked Docker data to /var/lib/docker..."
    cp -a "$BAKED_DIR/." /var/lib/docker/
    echo "Baked data copied ($(du -sh /var/lib/docker | cut -f1))"
    SKIP_IMAGE_LOAD=true
fi

# ─── DinD setup ──────────────────────────────────────────────────────────
rm -f /var/run/docker.pid
dockerd --host=unix:///var/run/docker.sock &

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

# ─── Verify or load images ──────────────────────────────────────────────
EMULATOR_IMAGE="${EMULATOR_IMAGE:-cybench/mobilecybench-emulator:latest}"
AGENT_IMAGE="${AGENT_IMAGE:-cybench/mobilecybench:latest}"

if [ "$SKIP_IMAGE_LOAD" = true ]; then
    echo "Images pre-loaded from baked snapshot:"
    docker images
else
    echo "No baked data found, falling back to pull..."
    if [ "${EMULATOR_BACKEND:-container}" = "container" ]; then
        echo "Pre-pulling emulator image: $EMULATOR_IMAGE"
        docker pull "$EMULATOR_IMAGE" &
        PID_EMU=$!
    fi
    echo "Pre-pulling agent image: $AGENT_IMAGE"
    docker pull "$AGENT_IMAGE" &
    PID_AGT=$!
    [ -n "${PID_EMU:-}" ] && wait $PID_EMU
    wait $PID_AGT
fi

# Install package if needed (in case image was built without -e install)
if [ -f /mobilecybench/pyproject.toml ]; then
    cd /mobilecybench && pip install --no-cache-dir -e . >/dev/null 2>&1 || true
fi

# Start ADB server (listen on all interfaces for kali container access)
adb -a start-server

# ─── Build runner config with GKE overrides ─────────────────────────────────
CONFIG_SRC="/mobilecybench/runner_config.json"
CONFIG_DST="/tmp/runner_config.json"

EMULATOR_BACKEND="${EMULATOR_BACKEND:-container}"
DRY_RUN="${DRY_RUN:-false}"
GOLD_RUN="${GOLD_RUN:-false}"

if [ -f "$CONFIG_SRC" ]; then
    jq --arg model "$MODEL" \
       --arg vuln "$VULN_ID" \
       --arg em "$EMULATOR_BACKEND" \
       --argjson dryrun "$DRY_RUN" \
       --argjson goldrun "$GOLD_RUN" \
       '.emulator_display = "headless"
        | .emulator_backend = $em
        | .dry_run = $dryrun
        | .gold_run = $goldrun
        | if $model != "" then .model = $model else . end
        | if $vuln != "" then .synthetic_vuln_id = $vuln else . end' \
       "$CONFIG_SRC" > "$CONFIG_DST"
else
    echo "ERROR: $CONFIG_SRC not found"
    exit 1
fi

echo "Runner config:"
cat "$CONFIG_DST"

# ─── Run experiment ─────────────────────────────────────────────────────────
cd /mobilecybench
python3 runner.py "$APP_NAME" --config "$CONFIG_DST"
EXIT_CODE=$?

# ─── Upload results to GCS ──────────────────────────────────────────────────
if [ -n "$GCS_BUCKET" ] && [ -n "$MOBILECYBENCH_LOGS_DIR" ]; then
    RUN_ID="${RUN_ID:-$(date +%s)}"
    GCS_PATH="gs://$GCS_BUCKET/$APP_NAME/$VULN_ID/$MODEL/$RUN_ID/"
    echo "Uploading results to $GCS_PATH"
    gsutil -m cp -r "$MOBILECYBENCH_LOGS_DIR"/experiment_* "$GCS_PATH" 2>/dev/null || \
        echo "WARNING: GCS upload failed or no experiment logs found"
fi

exit $EXIT_CODE
