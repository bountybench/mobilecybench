#!/bin/bash
set -e

# Capture the pod's own entrypoint output in the same tree that gets uploaded
# to GCS. Kubernetes pod logs disappear with deleted pods unless cluster-level
# logging is enabled, so keep a local copy as a normal benchmark artifact.
export MOBILECYBENCH_LOGS_DIR="${MOBILECYBENCH_LOGS_DIR:-/mobilecybench/logs}"
ENTRYPOINT_LOG="${ENTRYPOINT_LOG:-$MOBILECYBENCH_LOGS_DIR/gke/entrypoint.log}"
CONFIG_DST=""
UPLOAD_EXIT_CODE=0
UPLOAD_DIRS=()
GCS_AUTH_PREFLIGHT_OK=1
UPLOAD_FAILURE_BUNDLE=""

append_unique_upload_dir() {
    local candidate="$1"
    local existing

    [ -n "$candidate" ] || return
    [ -e "$candidate" ] || return

    for existing in "${UPLOAD_DIRS[@]:-}"; do
        [ "$existing" = "$candidate" ] && return
    done
    UPLOAD_DIRS+=("$candidate")
}

discover_upload_dirs() {
    local summary
    local artifact

    UPLOAD_DIRS=()
    append_unique_upload_dir "$MOBILECYBENCH_LOGS_DIR/gke"

    while IFS= read -r summary; do
        append_unique_upload_dir "$(dirname "$summary")"
    done < <(find "$MOBILECYBENCH_LOGS_DIR" -maxdepth 3 -name run_summary.json -type f 2>/dev/null)

    while IFS= read -r artifact; do
        append_unique_upload_dir "$(dirname "$(dirname "$artifact")")"
    done < <(
        find "$MOBILECYBENCH_LOGS_DIR" -maxdepth 5 -type f \
            \( \
                -path '*/agent_run/agent.log' -o \
                -path '*/agent_run/conversation.jsonl' -o \
                -path '*/agent_run/result.json' \
            \) 2>/dev/null
    )

    while IFS= read -r artifact; do
        append_unique_upload_dir "$(dirname "$artifact")"
    done < <(
        find "$MOBILECYBENCH_LOGS_DIR" -maxdepth 4 -type f \
            \( \
                -name task.json -o \
                -name system_prompt.txt -o \
                -name apk_provenance.jsonl \
            \) 2>/dev/null
    )
}

write_gke_progress_artifacts() {
    mkdir -p "$MOBILECYBENCH_LOGS_DIR/gke"

    if [ -f "${CONFIG_DST:-}" ]; then
        cp "$CONFIG_DST" "$MOBILECYBENCH_LOGS_DIR/gke/runner_config.json" || true
    fi

    find "$MOBILECYBENCH_LOGS_DIR" -maxdepth 5 -type f | sort \
        > "$MOBILECYBENCH_LOGS_DIR/gke/log_files.txt" 2>/dev/null || true

    discover_upload_dirs
    printf '%s\n' "${UPLOAD_DIRS[@]}" \
        > "$MOBILECYBENCH_LOGS_DIR/gke/upload_manifest.txt" 2>/dev/null || true
}

record_gcs_auth_preflight() {
    local preflight_log="$MOBILECYBENCH_LOGS_DIR/gke/gcs_auth_preflight.txt"
    local auth_ok=1

    mkdir -p "$MOBILECYBENCH_LOGS_DIR/gke"

    {
        echo "timestamp=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        echo "bucket=gs://${GCS_BUCKET:-}"
        echo "run_id=${RUN_ID:-}"
        echo
    } > "$preflight_log"

    if [ -z "${GCS_BUCKET:-}" ]; then
        echo "skip: GCS_BUCKET is unset" >> "$preflight_log"
        GCS_AUTH_PREFLIGHT_OK=1
        return
    fi

    if command -v curl >/dev/null 2>&1; then
        echo "== metadata email ==" >> "$preflight_log"
        if ! curl -fsS \
            -H "Metadata-Flavor: Google" \
            http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/email \
            >> "$preflight_log" 2>&1
        then
            auth_ok=0
        fi
        echo >> "$preflight_log"
    fi

    if command -v gcloud >/dev/null 2>&1; then
        echo "== gcloud auth application-default print-access-token ==" >> "$preflight_log"
        if ! gcloud auth application-default print-access-token >> "$preflight_log" 2>&1; then
            auth_ok=0
        fi
        echo >> "$preflight_log"

        echo "== gcloud storage ls gs://${GCS_BUCKET}/ ==" >> "$preflight_log"
        if ! gcloud storage ls "gs://${GCS_BUCKET}/" >> "$preflight_log" 2>&1; then
            auth_ok=0
        fi
        echo >> "$preflight_log"
    fi

    GCS_AUTH_PREFLIGHT_OK="$auth_ok"
    if [ "$GCS_AUTH_PREFLIGHT_OK" -ne 1 ]; then
        echo "WARNING: GCS auth preflight failed; uploads may not work. See $preflight_log" \
            | tee -a "$preflight_log"
        if [ "${REQUIRE_GCS_AUTH_PREFLIGHT:-false}" = "true" ]; then
            echo "ERROR: REQUIRE_GCS_AUTH_PREFLIGHT=true and auth preflight failed" \
                | tee -a "$preflight_log" >&2
            exit 1
        fi
    else
        echo "GCS auth preflight ok" >> "$preflight_log"
    fi
}

gcs_glob_exists() {
    local pattern="$1"

    if command -v gcloud >/dev/null 2>&1 && gcloud storage ls --help >/dev/null 2>&1; then
        gcloud storage ls "$pattern" >/dev/null 2>&1
    else
        gsutil ls "$pattern" >/dev/null 2>&1
    fi
}

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
    find "$MOBILECYBENCH_LOGS_DIR" -maxdepth 4 -name task.json -type f \
        -exec cp {} "$failure_dir"/ \; 2>/dev/null || true
    find "$MOBILECYBENCH_LOGS_DIR" -maxdepth 4 -name system_prompt.txt -type f \
        -exec cp {} "$failure_dir"/ \; 2>/dev/null || true
    find "$MOBILECYBENCH_LOGS_DIR" -maxdepth 4 -name apk_provenance.jsonl -type f \
        -exec cp {} "$failure_dir"/ \; 2>/dev/null || true

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

create_upload_failure_bundle() {
    local failure_dir="$MOBILECYBENCH_LOGS_DIR/gke_failure/${RUN_ID:-unknown-run}"
    local bundle_tmp="/tmp/${RUN_ID:-unknown-run}-gke-artifacts.tar.gz"
    local bundle_dst="$failure_dir/upload_failure_bundle.tar.gz"
    local manifest="$failure_dir/manual_retrieval.txt"
    local rel
    local src
    local bundle_sources=()

    mkdir -p "$failure_dir"
    write_gke_progress_artifacts

    for src in "${UPLOAD_DIRS[@]:-}"; do
        [ -d "$src" ] || continue
        case "$src" in
            "$MOBILECYBENCH_LOGS_DIR")
                continue
                ;;
            "$MOBILECYBENCH_LOGS_DIR"/*)
                rel="${src#"$MOBILECYBENCH_LOGS_DIR"/}"
                ;;
            *)
                continue
                ;;
        esac
        bundle_sources+=("$rel")
    done

    if [ ${#bundle_sources[@]} -eq 0 ]; then
        return
    fi

    rm -f "$bundle_tmp"
    if tar -C "$MOBILECYBENCH_LOGS_DIR" -czf "$bundle_tmp" "${bundle_sources[@]}"; then
        cp "$bundle_tmp" "$bundle_dst"
        if command -v shasum >/dev/null 2>&1; then
            shasum -a 256 "$bundle_dst" > "$bundle_dst.sha256" || true
        elif command -v sha256sum >/dev/null 2>&1; then
            sha256sum "$bundle_dst" > "$bundle_dst.sha256" || true
        fi
        UPLOAD_FAILURE_BUNDLE="$bundle_dst"
        {
            echo "GCS upload failed; retrieve the preserved artifact bundle with:"
            echo "  kubectl cp ${POD_NAMESPACE:-mobilecybench}/${RUN_ID:-unknown-run}:$bundle_dst ./$(basename "$bundle_dst")"
            echo
            echo "Bundle sources:"
            printf '  %s\n' "${bundle_sources[@]}"
        } > "$manifest"
        echo "Preserved manual-retrieval bundle at $bundle_dst"
        cat "$manifest"
    else
        echo "WARNING: failed to create upload fallback bundle $bundle_tmp" >&2
    fi
}

hold_for_manual_artifact_copy() {
    local hold_seconds="${UPLOAD_FAILURE_HOLD_SECONDS:-1800}"

    if [ -z "${UPLOAD_FAILURE_BUNDLE:-}" ] || [ ! -f "${UPLOAD_FAILURE_BUNDLE:-}" ]; then
        return
    fi
    if ! [[ "$hold_seconds" =~ ^[0-9]+$ ]]; then
        echo "WARNING: invalid UPLOAD_FAILURE_HOLD_SECONDS=$hold_seconds; skipping hold" >&2
        return
    fi
    if [ "$hold_seconds" -le 0 ]; then
        return
    fi

    echo "Holding container for ${hold_seconds}s so artifacts can be copied manually."
    echo "Run:"
    echo "  kubectl cp ${POD_NAMESPACE:-mobilecybench}/${RUN_ID:-unknown-run}:${UPLOAD_FAILURE_BUNDLE} ./$(basename "$UPLOAD_FAILURE_BUNDLE")"
    sleep "$hold_seconds"
}

perform_gcs_upload() {
    local run_exit_code="$1"
    local GCS_PATH
    local upload_ok
    local has_local_summary=0
    local has_local_agent_log=0
    local has_local_conversation=0
    local has_local_result_json=0
    local has_local_task_json=0
    local has_local_system_prompt=0
    local has_local_apk_provenance=0

    UPLOAD_EXIT_CODE=0
    if [ -z "${GCS_BUCKET:-}" ] || [ -z "${MOBILECYBENCH_LOGS_DIR:-}" ]; then
        return
    fi

    GCS_PATH="gs://$GCS_BUCKET/$APP_NAME/$VULN_ID/$MODEL/$RUN_ID/"
    echo "Uploading results to $GCS_PATH"

    write_gke_progress_artifacts

    if find "$MOBILECYBENCH_LOGS_DIR" -maxdepth 3 -name run_summary.json -type f \
        -print -quit 2>/dev/null | grep -q .
    then
        has_local_summary=1
    fi
    find "$MOBILECYBENCH_LOGS_DIR" -maxdepth 5 -path '*/agent_run/agent.log' -type f \
        -print -quit 2>/dev/null | grep -q . && has_local_agent_log=1
    find "$MOBILECYBENCH_LOGS_DIR" -maxdepth 5 -path '*/agent_run/conversation.jsonl' -type f \
        -print -quit 2>/dev/null | grep -q . && has_local_conversation=1
    find "$MOBILECYBENCH_LOGS_DIR" -maxdepth 5 -path '*/agent_run/result.json' -type f \
        -print -quit 2>/dev/null | grep -q . && has_local_result_json=1
    find "$MOBILECYBENCH_LOGS_DIR" -maxdepth 4 -name task.json -type f \
        -print -quit 2>/dev/null | grep -q . && has_local_task_json=1
    find "$MOBILECYBENCH_LOGS_DIR" -maxdepth 4 -name system_prompt.txt -type f \
        -print -quit 2>/dev/null | grep -q . && has_local_system_prompt=1
    find "$MOBILECYBENCH_LOGS_DIR" -maxdepth 4 -name apk_provenance.jsonl -type f \
        -print -quit 2>/dev/null | grep -q . && has_local_apk_provenance=1

    if [ ${#UPLOAD_DIRS[@]} -gt 0 ]; then
        upload_ok=0
        if command -v gcloud >/dev/null 2>&1 && gcloud storage cp --help >/dev/null 2>&1; then
            gcloud storage cp -r "${UPLOAD_DIRS[@]}" "$GCS_PATH" && upload_ok=1 || \
                gsutil -m cp -r "${UPLOAD_DIRS[@]}" "$GCS_PATH" && upload_ok=1 || true
        else
            gsutil -m cp -r "${UPLOAD_DIRS[@]}" "$GCS_PATH" && upload_ok=1 || true
        fi
        if [ "$upload_ok" -eq 1 ]; then
            gcs_glob_exists "${GCS_PATH}**/entrypoint.log" || upload_ok=0
        fi
        if [ "$upload_ok" -eq 1 ] && [ "$has_local_summary" -eq 1 ]; then
            gcs_glob_exists "${GCS_PATH}**/run_summary.json" || upload_ok=0
        fi
        if [ "$upload_ok" -eq 1 ] && [ "$has_local_agent_log" -eq 1 ]; then
            gcs_glob_exists "${GCS_PATH}**/agent.log" || upload_ok=0
        fi
        if [ "$upload_ok" -eq 1 ] && [ "$has_local_conversation" -eq 1 ]; then
            gcs_glob_exists "${GCS_PATH}**/conversation.jsonl" || upload_ok=0
        fi
        if [ "$upload_ok" -eq 1 ] && [ "$has_local_result_json" -eq 1 ]; then
            gcs_glob_exists "${GCS_PATH}**/result.json" || upload_ok=0
        fi
        if [ "$upload_ok" -eq 1 ] && [ "$has_local_task_json" -eq 1 ]; then
            gcs_glob_exists "${GCS_PATH}**/task.json" || upload_ok=0
        fi
        if [ "$upload_ok" -eq 1 ] && [ "$has_local_system_prompt" -eq 1 ]; then
            gcs_glob_exists "${GCS_PATH}**/system_prompt.txt" || upload_ok=0
        fi
        if [ "$upload_ok" -eq 1 ] && [ "$has_local_apk_provenance" -eq 1 ]; then
            gcs_glob_exists "${GCS_PATH}**/apk_provenance.jsonl" || upload_ok=0
        fi
        if [ "$upload_ok" -eq 1 ] && [ "$has_local_summary" -eq 0 ] && \
            [ "$has_local_agent_log" -eq 0 ] && \
            [ "$has_local_conversation" -eq 0 ] && \
            [ "$has_local_result_json" -eq 0 ] && \
            [ "$has_local_task_json" -eq 0 ] && \
            [ "$has_local_system_prompt" -eq 0 ] && \
            [ "$has_local_apk_provenance" -eq 0 ] && \
            [ "${DRY_RUN:-false}" != "true" ] && [ "$run_exit_code" -eq 0 ]
        then
            echo "ERROR: no experiment logs found to upload" >&2
            UPLOAD_EXIT_CODE=1
            return
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
}

finalize_gke_exit() {
    local exit_code="$1"
    local final_exit_code="$exit_code"

    trap - EXIT
    set +e
    RUN_ID="${RUN_ID:-$(date +%s)}"
    collect_gke_failure_artifacts "$exit_code"
    perform_gcs_upload "$exit_code"
    if [ "$UPLOAD_EXIT_CODE" -ne 0 ]; then
        create_upload_failure_bundle
        hold_for_manual_artifact_copy
        if [ "$exit_code" -eq 0 ] && [ -n "${UPLOAD_FAILURE_BUNDLE:-}" ] && [ -f "${UPLOAD_FAILURE_BUNDLE:-}" ]; then
            echo "Experiment finished successfully, but artifact upload failed."
            echo "Manual-retrieval bundle preserved; exiting 0 to avoid a duplicate Kubernetes retry."
            final_exit_code=0
        elif [ "$exit_code" -eq 0 ]; then
            final_exit_code="$UPLOAD_EXIT_CODE"
        fi
    fi

    exit "$final_exit_code"
}

trap 'finalize_gke_exit "$?"' EXIT
mkdir -p "$MOBILECYBENCH_LOGS_DIR/gke"
exec > >(tee -a "$ENTRYPOINT_LOG") 2>&1

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
   --arg network_mode "${NETWORK_MODE:-}" \
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
    | if $network_mode != "" then .network_mode = $network_mode else . end
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
record_gcs_auth_preflight
set +e
python3 runner.py "$APP_NAME" --config "$CONFIG_DST"
EXIT_CODE=$?
set -e
exit "$EXIT_CODE"
