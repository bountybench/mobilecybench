#!/bin/bash
set -e

# Capture the pod's own entrypoint output in the same tree that gets uploaded
# to GCS. Kubernetes pod logs disappear with deleted pods unless cluster-level
# logging is enabled, so keep a local copy as a normal benchmark artifact.
export MOBILECYBENCH_LOGS_DIR="${MOBILECYBENCH_LOGS_DIR:-/mobilecybench/logs}"
mkdir -p "$MOBILECYBENCH_LOGS_DIR/gke"
ENTRYPOINT_LOG="${ENTRYPOINT_LOG:-$MOBILECYBENCH_LOGS_DIR/gke/entrypoint.log}"
exec > >(tee -a "$ENTRYPOINT_LOG") 2>&1

collect_gke_failure_artifacts() {
    local exit_code="$1"
    local failure_dir="$MOBILECYBENCH_LOGS_DIR/gke_failure/${RUN_ID:-unknown-run}"

    if [ "$exit_code" -eq 0 ]; then
        return
    fi

    echo "Collecting GKE failure artifacts in $failure_dir"
    mkdir -p "$failure_dir"

    if [ -f "${CONFIG_DST:-}" ]; then
        cp "$CONFIG_DST" "$failure_dir/runner_config.json" || true
    fi
    if [ -f "$ENTRYPOINT_LOG" ]; then
        cp "$ENTRYPOINT_LOG" "$failure_dir/entrypoint.log" || true
    fi

    {
        for name in \
            APP_NAME VULN_ID MODEL RUN_ID AGENT_MODE AGENT_IMAGE WORKFLOW \
            PROBE_ONLY ATTACKER_MODEL BUILD_TYPE NO_CODEBASE APK_OBFUSCATION \
            EMULATOR_BACKEND DRY_RUN GOLD_RUN REASONING_EFFORT \
            MAX_ITERATIONS AGENT_WALLCLOCK_SECONDS
        do
            printf '%s=%q\n' "$name" "${!name-}"
        done
    } > "$failure_dir/gke_env.txt"

    docker ps -a > "$failure_dir/docker_ps.txt" 2>&1 || true
    docker network ls > "$failure_dir/docker_networks.txt" 2>&1 || true
    adb devices -l > "$failure_dir/adb_devices.txt" 2>&1 || true
    df -h > "$failure_dir/df_h.txt" 2>&1 || true
    find "$MOBILECYBENCH_LOGS_DIR" -maxdepth 4 -type f \
        > "$failure_dir/log_files.txt" 2>&1 || true

    if command -v jq >/dev/null 2>&1; then
        jq -n \
          --arg app "${APP_NAME:-}" \
          --arg model "${MODEL:-}" \
          --arg run_id "${RUN_ID:-}" \
          --arg vuln_id "${VULN_ID:-}" \
          --arg workflow "${WORKFLOW:-}" \
          --arg agent_mode "${AGENT_MODE:-}" \
          --arg agent_image "${AGENT_IMAGE:-}" \
          --arg failure_dir "$failure_dir" \
          --argjson exit_code "$exit_code" \
          '{
            context: {
              app_name: $app,
              model: $model,
              run_id: $run_id,
              vuln_id: $vuln_id,
              workflow: $workflow,
              agent_mode: $agent_mode,
              agent_image: $agent_image
            },
            results: {
              status: "failed",
              exit_code: $exit_code,
              failure_artifacts_dir: $failure_dir
            }
          }' > "$failure_dir/run_summary.json" || true
    fi

    if [ ! -f "$failure_dir/run_summary.json" ]; then
        printf '{"context":{"app_name":"%s","model":"%s","run_id":"%s"},"results":{"status":"failed","exit_code":%s}}\n' \
            "${APP_NAME:-}" "${MODEL:-}" "${RUN_ID:-}" "$exit_code" \
            > "$failure_dir/run_summary.json"
    fi
}

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
CONFIG_SRC="/mobilecybench/runner_config.json"
CONFIG_DST="/tmp/runner_config.json"

if [ ! -f "$CONFIG_SRC" ]; then
    echo "ERROR: $CONFIG_SRC not found" >&2
    exit 1
fi

EMULATOR_BACKEND="${EMULATOR_BACKEND:-container}"

normalize_bool() {
    case "$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')" in
        true | 1) echo true ;;
        *) echo false ;;
    esac
}

DRY_RUN="$(normalize_bool "${DRY_RUN:-false}")"
GOLD_RUN="$(normalize_bool "${GOLD_RUN:-false}")"

# Optional booleans: normalize only when explicitly set. Empty string is the
# "unset" sentinel the jq filter below checks before overriding.
PROBE_ONLY_B=""
[ -n "${PROBE_ONLY:-}" ] && PROBE_ONLY_B="$(normalize_bool "$PROBE_ONLY")"
NO_CODEBASE_B=""
[ -n "${NO_CODEBASE:-}" ] && NO_CODEBASE_B="$(normalize_bool "$NO_CODEBASE")"

jq --arg model "${MODEL:-}" \
   --arg vuln "${VULN_ID:-}" \
   --arg em "$EMULATOR_BACKEND" \
   --arg agent_image "${AGENT_IMAGE:-}" \
   --arg agent_mode "${AGENT_MODE:-}" \
   --arg build_type "${BUILD_TYPE:-}" \
   --arg workflow "${WORKFLOW:-}" \
   --arg attacker "${ATTACKER_MODEL:-}" \
   --arg probe_only "$PROBE_ONLY_B" \
   --arg no_codebase "$NO_CODEBASE_B" \
   --arg apk_obfuscation "${APK_OBFUSCATION:-}" \
   --arg max_iterations "${MAX_ITERATIONS:-}" \
   --arg wallclock "${AGENT_WALLCLOCK_SECONDS:-}" \
   --arg reasoning "${REASONING_EFFORT:-}" \
   --arg additional_system_prompt "${ADDITIONAL_SYSTEM_PROMPT:-}" \
   --argjson dryrun "$DRY_RUN" \
   --argjson goldrun "$GOLD_RUN" \
   '.emulator_display = "headless"
    | .emulator_backend = $em
    | .dry_run = $dryrun
    | .gold_run = $goldrun
    | if $model != "" then .model = $model else . end
    | if $vuln != "" then .synthetic_vuln_id = $vuln else . end
    | if $agent_image != "" then .agent_image = $agent_image else . end
    | if $agent_mode != "" then .agent_mode = $agent_mode else . end
    | if $build_type != "" then .build_type = $build_type else . end
    | if $workflow != "" then .workflow = $workflow else . end
    | if $attacker != "" then .attacker_model = $attacker else . end
    | if $no_codebase != "" then .no_codebase = ($no_codebase == "true") else . end
    | if $apk_obfuscation != "" then .apk_obfuscation = $apk_obfuscation else . end
    | if $max_iterations != "" then .max_iterations = ($max_iterations | tonumber) else . end
    | if $wallclock != "" then .agent_wallclock_seconds = ($wallclock | tonumber) else . end
    | if $reasoning != "" then .reasoning_effort = $reasoning else . end
    | if $additional_system_prompt != "" then .additional_system_prompt = $additional_system_prompt else . end
    | if $probe_only == "true" then
          .probe_only = true | .synthetic_vuln_id = null | .task = null
      elif $probe_only == "false" then
          .probe_only = false
      else . end' \
   "$CONFIG_SRC" > "$CONFIG_DST"

echo "Runner config:"
cat "$CONFIG_DST"

# Keep shell-side app scripts aligned with the runner config. Some runtime
# helpers (notably app-specific setup shells) key off MCB_OBFUSCATE to choose
# apk/ vs apk/obfuscated/ layout, so mirror the resolved config here before the
# Python runner starts.
if jq -e '.apk_obfuscation == "on"' "$CONFIG_DST" >/dev/null 2>&1; then
    export MCB_OBFUSCATE=1
else
    unset MCB_OBFUSCATE || true
fi

cd /mobilecybench
set +e
python3 runner.py "$APP_NAME" --config "$CONFIG_DST"
EXIT_CODE=$?
set -e
RUN_ID="${RUN_ID:-$(date +%s)}"
collect_gke_failure_artifacts "$EXIT_CODE"

# ─── Upload results to GCS ──────────────────────────────────────────────────
UPLOAD_EXIT_CODE=0
if [ -n "$GCS_BUCKET" ] && [ -n "$MOBILECYBENCH_LOGS_DIR" ]; then
    GCS_PATH="gs://$GCS_BUCKET/$APP_NAME/$VULN_ID/$MODEL/$RUN_ID/"
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
        upload_ok=0
        if command -v gcloud >/dev/null 2>&1 && gcloud storage cp --help >/dev/null 2>&1; then
            gcloud storage cp -r "${dirs[@]}" "$GCS_PATH" && upload_ok=1 || \
                gsutil -m cp -r "${dirs[@]}" "$GCS_PATH" && upload_ok=1 || true
        else
            gsutil -m cp -r "${dirs[@]}" "$GCS_PATH" && upload_ok=1 || true
        fi
        if [ "$upload_ok" -eq 1 ]; then
            if command -v gcloud >/dev/null 2>&1 && gcloud storage ls --help >/dev/null 2>&1; then
                gcloud storage ls "${GCS_PATH}**/run_summary.json" >/dev/null 2>&1 || upload_ok=0
            else
                gsutil ls "${GCS_PATH}**/run_summary.json" >/dev/null 2>&1 || upload_ok=0
            fi
        fi
        if [ "$upload_ok" -ne 1 ]; then
            echo "ERROR: GCS upload verification failed for $GCS_PATH" >&2
            UPLOAD_EXIT_CODE=1
        else
            echo "Verified GCS upload at $GCS_PATH"
        fi
    else
        if [ "${DRY_RUN:-false}" = "true" ]; then
            echo "Dry run produced no experiment logs; skipping upload verification"
        else
            echo "ERROR: no experiment logs found to upload" >&2
            UPLOAD_EXIT_CODE=1
        fi
    fi
fi

if [ "$EXIT_CODE" -eq 0 ] && [ "$UPLOAD_EXIT_CODE" -ne 0 ]; then
    exit "$UPLOAD_EXIT_CODE"
fi
exit $EXIT_CODE
