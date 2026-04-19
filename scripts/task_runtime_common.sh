#!/usr/bin/env bash
# Shared helpers for running task hooks, exploit containers, and verifiers.
# Sourced by both synthetic-task and zero-day-task validation paths.

# Global context set by task_runtime_set_context().
declare -a TASK_RUNTIME_ENV=()
TASK_RUNTIME_TASK_DIR=""
TASK_RUNTIME_OUTPUT_DIR=""
TASK_RUNTIME_APP_DIR=""
TASK_RUNTIME_TASK_METADATA_JSON=""
TASK_RUNTIME_APP_METADATA_JSON=""
TASK_RUNTIME_PACKAGE_NAME=""
TASK_RUNTIME_TASK_ID=""
TASK_RUNTIME_BASELINE_COMMIT=""
TASK_RUNTIME_ATTACK_MODEL=""
TASK_RUNTIME_PHASE=""
TASK_RUNTIME_FIX_PATCH=""
TASK_RUNTIME_WORKSPACE_DIR=""
TASK_RUNTIME_VERIFY_EXIT=255

task_runtime_clear_context() {
    TASK_RUNTIME_ENV=()
    TASK_RUNTIME_TASK_DIR=""
    TASK_RUNTIME_OUTPUT_DIR=""
    TASK_RUNTIME_APP_DIR=""
    TASK_RUNTIME_TASK_METADATA_JSON=""
    TASK_RUNTIME_APP_METADATA_JSON=""
    TASK_RUNTIME_PACKAGE_NAME=""
    TASK_RUNTIME_TASK_ID=""
    TASK_RUNTIME_BASELINE_COMMIT=""
    TASK_RUNTIME_ATTACK_MODEL=""
    TASK_RUNTIME_PHASE=""
    TASK_RUNTIME_FIX_PATCH=""
    TASK_RUNTIME_WORKSPACE_DIR=""
    TASK_RUNTIME_VERIFY_EXIT=255
}

task_runtime_set_context() {
    # 8 required positional slots + up to 4 optional. Keep this strict so
    # positional-shift regressions fail loudly before exporting a bad runtime
    # context.
    if [ "$#" -lt 8 ] || [ "$#" -gt 12 ]; then
        task_runtime_clear_context
        echo -e "${ERROR} task_runtime_set_context: expected 8-12 args, got $#"
        return 1
    fi

    local task_dir="$1"
    local output_dir="$2"
    local app_dir="$3"
    local task_metadata_json="$4"
    local app_metadata_json="$5"
    local package_name="$6"
    local task_id="$7"
    local baseline_commit="$8"
    local attack_model="${9:-}"
    local phase="${10:-}"
    local fix_patch="${11:-}"
    local workspace_dir="${12:-}"
    local -a task_runtime_env=()

    case "$attack_model" in
        ""|malicious_app|remote_attacker) ;;
        *)
            task_runtime_clear_context
            echo -e "${ERROR} task_runtime_set_context: invalid attack_model '$attack_model' (expected: empty, malicious_app, remote_attacker)"
            return 1
            ;;
    esac

    TASK_RUNTIME_TASK_DIR="$task_dir"
    TASK_RUNTIME_OUTPUT_DIR="$output_dir"
    TASK_RUNTIME_APP_DIR="$app_dir"
    TASK_RUNTIME_TASK_METADATA_JSON="$task_metadata_json"
    TASK_RUNTIME_APP_METADATA_JSON="$app_metadata_json"
    TASK_RUNTIME_PACKAGE_NAME="$package_name"
    TASK_RUNTIME_TASK_ID="$task_id"
    TASK_RUNTIME_BASELINE_COMMIT="$baseline_commit"
    TASK_RUNTIME_ATTACK_MODEL="$attack_model"
    TASK_RUNTIME_PHASE="$phase"
    TASK_RUNTIME_FIX_PATCH="$fix_patch"
    TASK_RUNTIME_WORKSPACE_DIR="$workspace_dir"

    task_runtime_env=()
    if [ -n "${ANDROID_SERIAL:-}" ]; then
        task_runtime_env+=("ANDROID_SERIAL=$ANDROID_SERIAL")
    fi
    task_runtime_env+=(
        "MCB_TASK_DIR=$TASK_RUNTIME_TASK_DIR"
        "MCB_OUTPUT_DIR=$TASK_RUNTIME_OUTPUT_DIR"
        "MCB_APP_DIR=$TASK_RUNTIME_APP_DIR"
        "MCB_TASK_METADATA_JSON=$TASK_RUNTIME_TASK_METADATA_JSON"
        "MCB_APP_METADATA_JSON=$TASK_RUNTIME_APP_METADATA_JSON"
        "MCB_PACKAGE_NAME=$TASK_RUNTIME_PACKAGE_NAME"
        "MCB_TASK_ID=$TASK_RUNTIME_TASK_ID"
        "MCB_BASELINE_COMMIT=$TASK_RUNTIME_BASELINE_COMMIT"
        "MCB_ATTACK_MODEL=$TASK_RUNTIME_ATTACK_MODEL"
        "MCB_PHASE=$TASK_RUNTIME_PHASE"
    )
    if [ -n "$TASK_RUNTIME_FIX_PATCH" ]; then
        task_runtime_env+=("MCB_FIX_PATCH=$TASK_RUNTIME_FIX_PATCH")
    fi
    if [ -n "$TASK_RUNTIME_WORKSPACE_DIR" ]; then
        task_runtime_env+=("MCB_WORKSPACE_DIR=$TASK_RUNTIME_WORKSPACE_DIR")
    fi

    TASK_RUNTIME_ENV=("${task_runtime_env[@]}")
}

task_runtime_run_prepare_hook() {
    local log_file="${1:-}"
    local prepare_hook="$TASK_RUNTIME_TASK_DIR/prepare_app.sh"

    [ -f "$prepare_hook" ] || return 0

    echo -e "${INFO} Running prepare_app.sh..."
    if [ -n "$log_file" ]; then
        if ! (
            cd "$TASK_RUNTIME_TASK_DIR" && \
            env "${TASK_RUNTIME_ENV[@]}" timeout 300 bash "$prepare_hook" >"$log_file" 2>&1
        ); then
            cat "$log_file" >&2 || true
            echo -e "${ERROR} prepare_app.sh failed or timed out"
            return 1
        fi
        cat "$log_file" || true
    else
        if ! (
            cd "$TASK_RUNTIME_TASK_DIR" && \
            env "${TASK_RUNTIME_ENV[@]}" timeout 300 bash "$prepare_hook"
        ); then
            echo -e "${ERROR} prepare_app.sh failed or timed out"
            return 1
        fi
    fi

    echo -e "${SUCCESS} prepare_app.sh completed"
}

task_runtime_run_exploit_container() {
    local root_dir="$1"
    local codebase_dir="$2"
    local log_file="${3:-}"

    echo -e "${INFO} Executing exploit in container..."
    if [ -n "$log_file" ]; then
        (
            cd "$TASK_RUNTIME_TASK_DIR" && \
            env "${TASK_RUNTIME_ENV[@]}" "$root_dir/utils/run_exploit_container.sh" \
                --exploit-dir "$TASK_RUNTIME_TASK_DIR/exploit_files" \
                --output-dir "$TASK_RUNTIME_OUTPUT_DIR" \
                --image "${EXPLOIT_IMAGE:-cybench/mobilecybench:latest}" \
                --utils-dir "$root_dir/utils" \
                --codebase-dir "$codebase_dir" \
                >"$log_file" 2>&1
        )
        local exploit_exit=$?
        cat "$log_file" || true
        return "$exploit_exit"
    fi

    (
        cd "$TASK_RUNTIME_TASK_DIR" && \
        env "${TASK_RUNTIME_ENV[@]}" "$root_dir/utils/run_exploit_container.sh" \
            --exploit-dir "$TASK_RUNTIME_TASK_DIR/exploit_files" \
            --output-dir "$TASK_RUNTIME_OUTPUT_DIR" \
            --image "${EXPLOIT_IMAGE:-cybench/mobilecybench:latest}" \
            --utils-dir "$root_dir/utils" \
            --codebase-dir "$codebase_dir"
    )
}

task_runtime_run_exploit_apk() {
    local root_dir="$1"
    local log_file="${2:-}"
    local apk_project_dir="$TASK_RUNTIME_TASK_DIR/exploit_files/exploit_apk"

    if [ ! -d "$apk_project_dir" ]; then
        echo -e "${ERROR} Required exploit APK directory not found: $apk_project_dir"
        return 1
    fi

    if [ ! -f "$apk_project_dir/build_exploit_apk.sh" ]; then
        cp "$root_dir/templates/malicious_apk/build_exploit_apk.sh" "$apk_project_dir/build_exploit_apk.sh"
        chmod +x "$apk_project_dir/build_exploit_apk.sh"
    fi

    echo -e "${INFO} Executing malicious APK replay on host..."
    local -a cmd=(
        python3 - "$root_dir" "$apk_project_dir" "$TASK_RUNTIME_OUTPUT_DIR" "${APK_TIMEOUT:-60}"
    )
    local script='from pathlib import Path
import sys

root_dir = Path(sys.argv[1])
apk_project_dir = Path(sys.argv[2])
output_dir = Path(sys.argv[3])
timeout = int(sys.argv[4])

sys.path.insert(0, str(root_dir))
from evaluation.replay_apk import replay_malicious_apk

result = replay_malicious_apk(apk_project_dir, output_dir, timeout=timeout)
raise SystemExit(result.exit_code)'

    if [ -n "$log_file" ]; then
        env "${TASK_RUNTIME_ENV[@]}" "${cmd[@]}" >"$log_file" 2>&1 <<<"$script"
        return $?
    fi
    env "${TASK_RUNTIME_ENV[@]}" "${cmd[@]}" <<<"$script"
}

task_runtime_run_exploit() {
    local root_dir="$1"
    local codebase_dir="$2"
    local log_file="${3:-}"

    case "$TASK_RUNTIME_ATTACK_MODEL" in
        malicious_app)
            task_runtime_run_exploit_apk "$root_dir" "$log_file"
            ;;
        *)
            task_runtime_run_exploit_container "$root_dir" "$codebase_dir" "$log_file"
            ;;
    esac
}

task_runtime_run_verifier() {
    local log_file="${1:-}"
    local verify_script="$TASK_RUNTIME_TASK_DIR/verify_files/verify_exploit.sh"
    local errexit_was_set=false
    case "$-" in
        *e*) errexit_was_set=true ;;
    esac

    echo -e "${INFO} Running verification..."
    chmod +x "$verify_script"

    set +e
    if [ -n "$log_file" ]; then
        (
            cd "$TASK_RUNTIME_TASK_DIR" && \
            env "${TASK_RUNTIME_ENV[@]}" bash "$verify_script" >"$log_file" 2>&1
        )
        TASK_RUNTIME_VERIFY_EXIT=$?
        cat "$log_file" || true
    else
        (
            cd "$TASK_RUNTIME_TASK_DIR" && \
            env "${TASK_RUNTIME_ENV[@]}" bash "$verify_script"
        )
        TASK_RUNTIME_VERIFY_EXIT=$?
    fi
    if [ "$errexit_was_set" = true ]; then
        set -e
    fi
}

task_runtime_check_expectation() {
    local expect_vulnerable="$1"
    local subject="$2"

    if [ "$TASK_RUNTIME_VERIFY_EXIT" -gt 1 ]; then
        echo -e "${ERROR} Verifier failed with unexpected exit code $TASK_RUNTIME_VERIFY_EXIT"
        return 1
    fi

    if [ "$expect_vulnerable" = "true" ]; then
        if [ "$TASK_RUNTIME_VERIFY_EXIT" -eq 0 ]; then
            echo -e "${SUCCESS} $subject is vulnerable (as expected)"
            return 0
        fi
        echo -e "${ERROR} $subject is NOT vulnerable (expected verifier exit 0, got $TASK_RUNTIME_VERIFY_EXIT)"
        return 1
    fi

    if [ "$TASK_RUNTIME_VERIFY_EXIT" -eq 1 ]; then
        echo -e "${SUCCESS} $subject is not vulnerable (as expected)"
        return 0
    fi
    echo -e "${ERROR} $subject is vulnerable (expected verifier exit 1, got $TASK_RUNTIME_VERIFY_EXIT)"
    return 1
}
