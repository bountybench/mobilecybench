#!/bin/bash
set -e

# ─── DinD setup (same as orchestrator/entrypoint.sh) ───────────────────────
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

# Install package if needed (in case image was built without -e install)
if [ -f /mobilecybench/pyproject.toml ]; then
    cd /mobilecybench && pip install --no-cache-dir -e . >/dev/null 2>&1 || true
fi

# Start ADB server (listen on all interfaces for kali container access)
adb -a start-server

# ─── Build runner config with GKE overrides ─────────────────────────────────
CONFIG_SRC="/mobilecybench/runner_config.json"
CONFIG_DST="/tmp/runner_config.json"

EMULATOR_MODE="${EMULATOR_MODE:-container}"
DRY_RUN="${DRY_RUN:-false}"
GOLD_RUN="${GOLD_RUN:-false}"

if [ -f "$CONFIG_SRC" ]; then
    jq --arg model "$MODEL" \
       --arg vuln "$VULN_ID" \
       --arg em "$EMULATOR_MODE" \
       --argjson dryrun "$DRY_RUN" \
       --argjson goldrun "$GOLD_RUN" \
       '.docker_mode = true
        | .emulator_mode = $em
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
