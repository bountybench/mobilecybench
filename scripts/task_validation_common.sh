#!/usr/bin/env bash
# Shared helpers for task validation flows that install APKs, wait for app
# services, run task hooks, and verify comparator expectations.

if [ -n "${TASK_VALIDATION_COMMON_SH_LOADED:-}" ]; then
    return 0 2>/dev/null || exit 0
fi
TASK_VALIDATION_COMMON_SH_LOADED=1

if [ -z "${ROOT_DIR:-}" ]; then
    echo "ROOT_DIR must be set before sourcing scripts/task_validation_common.sh" >&2
    return 1 2>/dev/null || exit 1
fi

source "${ROOT_DIR}/scripts/task_runtime_common.sh"

TASK_VALIDATION_ROOT_DIR=""
TASK_VALIDATION_APP_DIR=""
TASK_VALIDATION_TASK_DIR=""
TASK_VALIDATION_OUTPUT_ROOT=""
TASK_VALIDATION_LOG_ROOT=""
TASK_VALIDATION_ARTIFACTS_DIR=""
TASK_VALIDATION_PACKAGE_NAME=""
TASK_VALIDATION_TASK_ID=""
TASK_VALIDATION_BASELINE_COMMIT=""
TASK_VALIDATION_ATTACKER_MODEL=""
TASK_VALIDATION_FIX_PATCH=""
TASK_VALIDATION_WORKSPACE_DIR=""
TASK_VALIDATION_OUTPUT_MODE="per_phase"
TASK_VALIDATION_RESET_FLAT_OUTPUT=false
TASK_VALIDATION_TASK_METADATA_JSON=""
TASK_VALIDATION_APP_METADATA_JSON=""
TASK_VALIDATION_CODEBASE_DIR=""

task_validation_clear_context() {
    TASK_VALIDATION_ROOT_DIR=""
    TASK_VALIDATION_APP_DIR=""
    TASK_VALIDATION_TASK_DIR=""
    TASK_VALIDATION_OUTPUT_ROOT=""
    TASK_VALIDATION_LOG_ROOT=""
    TASK_VALIDATION_ARTIFACTS_DIR=""
    TASK_VALIDATION_PACKAGE_NAME=""
    TASK_VALIDATION_TASK_ID=""
    TASK_VALIDATION_BASELINE_COMMIT=""
    TASK_VALIDATION_ATTACKER_MODEL=""
    TASK_VALIDATION_FIX_PATCH=""
    TASK_VALIDATION_WORKSPACE_DIR=""
    TASK_VALIDATION_OUTPUT_MODE="per_phase"
    TASK_VALIDATION_RESET_FLAT_OUTPUT=false
    TASK_VALIDATION_TASK_METADATA_JSON=""
    TASK_VALIDATION_APP_METADATA_JSON=""
    TASK_VALIDATION_CODEBASE_DIR=""
}

_task_validation_log() {
    local level="$1"
    shift
    local prefix="${level}"
    case "$level" in
        INFO) prefix="${INFO:-[INFO]}" ;;
        SUCCESS) prefix="${SUCCESS:-[SUCCESS]}" ;;
        ERROR) prefix="${ERROR:-[ERROR]}" ;;
        WARNING) prefix="${WARNING:-[WARNING]}" ;;
    esac
    echo -e "${prefix} $*"
}

task_validation_set_context() {
    # 9 required positional args + up to 5 optional. Caller must pass all 9 so a
    # future positional-shift regression fails loudly instead of silently
    # misassigning downstream fields (see run_ci_local.sh synthetic caller).
    if [ "$#" -lt 9 ] || [ "$#" -gt 14 ]; then
        task_validation_clear_context
        _task_validation_log ERROR "task_validation_set_context: expected 9-14 args, got $#"
        return 1
    fi

    local root_dir="$1"
    local app_dir="$2"
    local task_dir="$3"
    local output_root="$4"
    local log_root="$5"
    local artifacts_dir="$6"
    local package_name="$7"
    local task_id="$8"
    local baseline_commit="$9"
    local attacker_model="${10:-}"
    local fix_patch="${11:-}"
    local workspace_dir="${12:-}"
    local output_mode="${13:-per_phase}"
    local reset_flat_output="${14:-false}"

    case "$attacker_model" in
        ""|malicious_app|remote_attacker) ;;
        *)
            task_validation_clear_context
            _task_validation_log ERROR "task_validation_set_context: invalid attacker_model '$attacker_model' (expected: empty, malicious_app, remote_attacker)"
            return 1
            ;;
    esac
    case "$output_mode" in
        per_phase|flat) ;;
        *)
            task_validation_clear_context
            _task_validation_log ERROR "task_validation_set_context: invalid output_mode '$output_mode' (expected: per_phase, flat)"
            return 1
            ;;
    esac
    case "$reset_flat_output" in
        true|false) ;;
        *)
            task_validation_clear_context
            _task_validation_log ERROR "task_validation_set_context: invalid reset_flat_output '$reset_flat_output' (expected: true, false)"
            return 1
            ;;
    esac

    TASK_VALIDATION_ROOT_DIR="$root_dir"
    TASK_VALIDATION_APP_DIR="$app_dir"
    TASK_VALIDATION_TASK_DIR="$task_dir"
    TASK_VALIDATION_OUTPUT_ROOT="$output_root"
    TASK_VALIDATION_LOG_ROOT="$log_root"
    TASK_VALIDATION_ARTIFACTS_DIR="$artifacts_dir"
    TASK_VALIDATION_PACKAGE_NAME="$package_name"
    TASK_VALIDATION_TASK_ID="$task_id"
    TASK_VALIDATION_BASELINE_COMMIT="$baseline_commit"
    TASK_VALIDATION_ATTACKER_MODEL="$attacker_model"
    TASK_VALIDATION_FIX_PATCH="$fix_patch"
    TASK_VALIDATION_WORKSPACE_DIR="$workspace_dir"
    TASK_VALIDATION_OUTPUT_MODE="$output_mode"
    TASK_VALIDATION_RESET_FLAT_OUTPUT="$reset_flat_output"
    TASK_VALIDATION_TASK_METADATA_JSON="$TASK_VALIDATION_TASK_DIR/metadata.json"
    TASK_VALIDATION_APP_METADATA_JSON="$TASK_VALIDATION_APP_DIR/metadata.json"
    TASK_VALIDATION_CODEBASE_DIR="$TASK_VALIDATION_APP_DIR/codebase"
}

task_validation_check_app_containers_ready() {
    local metadata_json="$1"
    local timeout="${TIMEOUT:-180}"
    local interval="${INTERVAL:-1}"
    local containers=""

    if [ -f "$metadata_json" ]; then
        containers=$(jq -r '.container_names[]? // empty' "$metadata_json" 2>/dev/null)
    fi

    if [ -z "$containers" ]; then
        _task_validation_log INFO "No app-specific containers found in metadata.json - skipping container readiness check"
        return 0
    fi

    _task_validation_log INFO "Checking readiness for app-specific containers: $containers"

    local container
    for container in $containers; do
        _task_validation_log INFO "Checking readiness for $container..."

        local has_health
        has_health=$(docker inspect --format '{{if .Config.Healthcheck}}true{{else}}false{{end}}' "$container" 2>/dev/null || true)
        if [ -z "$has_health" ]; then
            _task_validation_log ERROR "Container not found: $container"
            return 1
        fi

        if [ "$has_health" = "true" ]; then
            local elapsed=0
            local success=0
            while [ "$elapsed" -lt "$timeout" ]; do
                local status
                status=$(docker inspect --format '{{.State.Health.Status}}' "$container" 2>/dev/null || true)
                if [ "$status" = "healthy" ]; then
                    success=1
                    break
                fi
                sleep "$interval"
                elapsed=$((elapsed + interval))
            done
            if [ "$success" -eq 1 ]; then
                _task_validation_log INFO "$container is healthy."
                continue
            fi
            _task_validation_log ERROR "Timeout: $container did not become healthy within $timeout seconds."
            return 1
        fi

        local ports
        ports=$(docker inspect --format '{{range $p, $conf := .NetworkSettings.Ports}}{{range $conf}}{{.HostPort}} {{end}}{{end}}' "$container" 2>/dev/null || true)
        if [ -z "$ports" ]; then
            _task_validation_log WARNING "No exposed ports for $container. Skipping readiness check."
            continue
        fi

        local elapsed=0
        local all_success=0
        while [ "$elapsed" -lt "$timeout" ]; do
            local success=1
            local port
            for port in $ports; do
                if ! nc -z -w 1 localhost "$port" >/dev/null 2>&1; then
                    success=0
                    break
                fi
            done
            if [ "$success" -eq 1 ]; then
                all_success=1
                break
            fi
            sleep "$interval"
            elapsed=$((elapsed + interval))
        done

        if [ "$all_success" -eq 1 ]; then
            _task_validation_log INFO "$container is ready via port check on all ports."
        else
            _task_validation_log ERROR "Timeout: $container not ready after $timeout seconds."
            return 1
        fi
    done

    _task_validation_log INFO "App-specific containers are ready!"
    return 0
}

task_validation_resolve_android_serial() {
    if [ -n "${ANDROID_SERIAL:-}" ]; then
        _task_validation_log INFO "Using ANDROID_SERIAL from environment: $ANDROID_SERIAL"
        return 0
    fi

    local -a devices=()
    while IFS= read -r device; do
        [ -n "$device" ] || continue
        devices+=("$device")
    done < <(adb devices | awk '$2 == "device" { print $1 }')

    if [ ${#devices[@]} -eq 0 ]; then
        _task_validation_log ERROR "No online adb device found"
        return 1
    fi

    if [ ${#devices[@]} -gt 1 ]; then
        local preferred=""
        local device
        for device in "${devices[@]}"; do
            if [[ "$device" == emulator-* ]]; then
                preferred="$device"
                break
            fi
        done
        if [ -z "$preferred" ]; then
            preferred="${devices[0]}"
        fi
        export ANDROID_SERIAL="$preferred"
        _task_validation_log WARNING "Multiple adb devices detected (${devices[*]}); using $ANDROID_SERIAL"
        return 0
    fi

    export ANDROID_SERIAL="${devices[0]}"
    _task_validation_log INFO "Using adb device: $ANDROID_SERIAL"
    return 0
}

task_validation_uninstall_package() {
    local package_name="$1"
    if [ -z "$package_name" ]; then
        return 0
    fi
    if adb shell pm list packages 2>/dev/null | grep -q "^package:${package_name}$"; then
        _task_validation_log INFO "Uninstalling $package_name..."
        adb uninstall "$package_name" >/dev/null 2>&1 || true
    fi
}

task_validation_cleanup_runtime() {
    if [ -d "$TASK_VALIDATION_APP_DIR" ] && [ -x "$TASK_VALIDATION_APP_DIR/cleanup.sh" ]; then
        (
            cd "$TASK_VALIDATION_APP_DIR" && ./cleanup.sh
        ) >/dev/null 2>&1 || true
    fi
    task_validation_uninstall_package "$TASK_VALIDATION_PACKAGE_NAME" >/dev/null 2>&1 || true
}

task_validation_copy_phase_artifacts() {
    local phase_slug="$1"
    local phase_output="$2"
    local phase_logs="$3"

    if [ -z "$TASK_VALIDATION_ARTIFACTS_DIR" ]; then
        return 0
    fi

    local phase_artifacts="$TASK_VALIDATION_ARTIFACTS_DIR/$phase_slug"
    mkdir -p "$phase_artifacts"
    cp -R "$phase_output/." "$phase_artifacts/" 2>/dev/null || true
    if [ -n "$phase_logs" ] && [ -d "$phase_logs" ]; then
        cp -R "$phase_logs" "$phase_artifacts/logs" 2>/dev/null || true
    fi
    cp "$TASK_VALIDATION_TASK_METADATA_JSON" "$phase_artifacts/metadata.json" 2>/dev/null || true
    if [ -n "$TASK_VALIDATION_FIX_PATCH" ] && [ -f "$TASK_VALIDATION_FIX_PATCH" ]; then
        cp "$TASK_VALIDATION_FIX_PATCH" "$phase_artifacts/fix.patch" 2>/dev/null || true
    fi
}

task_validation_run_prepare_victim_hook() {
    local log_file="${1:-}"
    local prepare_victim_hook="$TASK_VALIDATION_APP_DIR/prepare_victim.sh"

    if [ ! -f "$prepare_victim_hook" ]; then
        _task_validation_log INFO "No prepare_victim.sh found — skipping victim setup"
        return 0
    fi

    echo -e "${INFO} Running prepare_victim.sh..."
    if [ -n "$log_file" ]; then
        if ! (
            cd "$TASK_VALIDATION_APP_DIR" && \
            env "${TASK_RUNTIME_ENV[@]}" timeout 300 bash "$prepare_victim_hook" >"$log_file" 2>&1
        ); then
            cat "$log_file" >&2 || true
            echo -e "${ERROR} prepare_victim.sh failed or timed out"
            return 1
        fi
        cat "$log_file" || true
    else
        if ! (
            cd "$TASK_VALIDATION_APP_DIR" && \
            env "${TASK_RUNTIME_ENV[@]}" timeout 300 bash "$prepare_victim_hook"
        ); then
            echo -e "${ERROR} prepare_victim.sh failed or timed out"
            return 1
        fi
    fi

    echo -e "${SUCCESS} prepare_victim.sh completed"
}

task_validation_clear_package_data() {
    local package_name="$1"
    local log_file="${2:-}"

    [ -n "$package_name" ] || return 0

    _task_validation_log INFO "Clearing app data (pm clear $package_name)"
    if [ -n "$log_file" ]; then
        if ! adb shell pm clear "$package_name" >"$log_file" 2>&1; then
            cat "$log_file" >&2 || true
            _task_validation_log ERROR "pm clear failed for $package_name"
            return 1
        fi
        cat "$log_file" || true
        return 0
    fi

    if ! adb shell pm clear "$package_name"; then
        _task_validation_log ERROR "pm clear failed for $package_name"
        return 1
    fi
}

task_validation_run_attacker_model_setup_before_exploit() {
    local victim_log="${1:-}"

    case "$TASK_VALIDATION_ATTACKER_MODEL" in
        malicious_app)
            task_validation_run_prepare_victim_hook "$victim_log"
            ;;
        *)
            return 0
            ;;
    esac
}

task_validation_run_attacker_model_setup_after_exploit() {
    local clear_log="${1:-}"
    local victim_log="${2:-}"

    case "$TASK_VALIDATION_ATTACKER_MODEL" in
        remote_attacker)
            task_validation_clear_package_data "$TASK_VALIDATION_PACKAGE_NAME" "$clear_log" || return 1
            task_validation_run_prepare_victim_hook "$victim_log"
            ;;
        *)
            return 0
            ;;
    esac
}

task_validation_run_phase() {
    local phase_name="$1"
    local phase_slug="$2"
    local apk_arg="$3"
    local expect_vulnerable="$4"
    local post_install_hook="${5:-}"

    local phase_output="$TASK_VALIDATION_OUTPUT_ROOT"
    if [ "$TASK_VALIDATION_OUTPUT_MODE" = "per_phase" ]; then
        phase_output="$TASK_VALIDATION_OUTPUT_ROOT/$phase_slug"
    elif [ "$TASK_VALIDATION_RESET_FLAT_OUTPUT" = true ]; then
        rm -rf "$phase_output"
    fi
    mkdir -p "$phase_output"

    local phase_logs=""
    local prepare_log=""
    local victim_log=""
    local exploit_log=""
    local clear_log=""
    local verify_log=""
    if [ -n "$TASK_VALIDATION_LOG_ROOT" ]; then
        phase_logs="$TASK_VALIDATION_LOG_ROOT/$phase_slug"
        rm -rf "$phase_logs"
        mkdir -p "$phase_logs"
        prepare_log="$phase_logs/prepare.log"
        victim_log="$phase_logs/prepare_victim.log"
        exploit_log="$phase_logs/exploit.log"
        clear_log="$phase_logs/pm_clear.log"
        verify_log="$phase_logs/verify.log"
    fi

    _task_validation_log INFO "=== Phase: $phase_name (expect_vulnerable=$expect_vulnerable) ==="

    _task_validation_log INFO "Installing APK..."
    cd "$TASK_VALIDATION_APP_DIR"
    if [ -n "$apk_arg" ]; then
        ./start_runtime.sh --apk "$apk_arg" || {
            _task_validation_log ERROR "start_runtime.sh failed"
            return 1
        }
    else
        ./start_runtime.sh || {
            _task_validation_log ERROR "start_runtime.sh failed"
            return 1
        }
    fi

    if ! adb shell pm list packages 2>/dev/null | grep -q "^package:${TASK_VALIDATION_PACKAGE_NAME}$"; then
        _task_validation_log ERROR "Package $TASK_VALIDATION_PACKAGE_NAME not installed after start_runtime.sh"
        return 1
    fi

    if ! task_validation_check_app_containers_ready "$TASK_VALIDATION_APP_METADATA_JSON"; then
        task_validation_copy_phase_artifacts "$phase_slug" "$phase_output" "$phase_logs"
        return 1
    fi

    if [ -n "$post_install_hook" ]; then
        if ! "$post_install_hook" "$phase_slug"; then
            task_validation_copy_phase_artifacts "$phase_slug" "$phase_output" "$phase_logs"
            return 1
        fi
    fi

    if ! task_runtime_set_context \
        "$TASK_VALIDATION_TASK_DIR" \
        "$phase_output" \
        "$TASK_VALIDATION_APP_DIR" \
        "$TASK_VALIDATION_TASK_METADATA_JSON" \
        "$TASK_VALIDATION_APP_METADATA_JSON" \
        "$TASK_VALIDATION_PACKAGE_NAME" \
        "$TASK_VALIDATION_TASK_ID" \
        "$TASK_VALIDATION_BASELINE_COMMIT" \
        "$TASK_VALIDATION_ATTACKER_MODEL" \
        "$phase_slug" \
        "$TASK_VALIDATION_FIX_PATCH" \
        "$TASK_VALIDATION_WORKSPACE_DIR"; then
        task_validation_copy_phase_artifacts "$phase_slug" "$phase_output" "$phase_logs"
        return 1
    fi

    if ! task_runtime_run_prepare_hook "$prepare_log"; then
        task_validation_copy_phase_artifacts "$phase_slug" "$phase_output" "$phase_logs"
        return 1
    fi

    if ! task_validation_run_attacker_model_setup_before_exploit "$victim_log"; then
        task_validation_copy_phase_artifacts "$phase_slug" "$phase_output" "$phase_logs"
        return 1
    fi

    if ! task_runtime_run_exploit \
        "$TASK_VALIDATION_ROOT_DIR" \
        "$TASK_VALIDATION_CODEBASE_DIR" \
        "$exploit_log"; then
        _task_validation_log WARNING "Exploit returned non-zero (may be expected)"
    fi

    if ! task_validation_run_attacker_model_setup_after_exploit "$clear_log" "$victim_log"; then
        task_validation_copy_phase_artifacts "$phase_slug" "$phase_output" "$phase_logs"
        return 1
    fi

    task_runtime_run_verifier "$verify_log"
    if ! task_runtime_check_expectation "$expect_vulnerable" "$phase_name"; then
        task_validation_copy_phase_artifacts "$phase_slug" "$phase_output" "$phase_logs"
        return 1
    fi

    task_validation_copy_phase_artifacts "$phase_slug" "$phase_output" "$phase_logs"
    return 0
}
