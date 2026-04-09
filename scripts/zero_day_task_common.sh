#!/usr/bin/env bash
# Shared zero-day task validation logic used by both run_ci_local.sh and the
# external-task CLI wrappers.

if [ -n "${ZERO_DAY_TASK_COMMON_SH_LOADED:-}" ]; then
    return 0 2>/dev/null || exit 0
fi
ZERO_DAY_TASK_COMMON_SH_LOADED=1

if [ -z "${ROOT_DIR:-}" ]; then
    echo "ROOT_DIR must be set before sourcing scripts/zero_day_task_common.sh" >&2
    return 1 2>/dev/null || exit 1
fi

source "${ROOT_DIR}/scripts/task_validation_common.sh"

declare -a ZERO_DAY_BUILD_ENV_ARGS=()
ZERO_DAY_WORKSPACE=""
ZERO_DAY_TASK_WORK_DIR=""
ZERO_DAY_TASK_METADATA=""
ZERO_DAY_TASK_ID=""
ZERO_DAY_PACKAGE_NAME=""
ZERO_DAY_BASELINE_COMMIT=""
ZERO_DAY_SECURE_PATCH_ABS=""

zero_day_task_resolve_abs_dir() {
    local dir="$1"
    if [ ! -d "$dir" ]; then
        _task_validation_log ERROR "Directory not found: $dir"
        return 1
    fi
    (
        cd "$dir" >/dev/null 2>&1 || exit 1
        pwd
    )
}

zero_day_task_validate_metadata_schema_if_present() {
    local metadata_file="$1"
    local schema_version
    schema_version="$(jq -r '.schema_version // empty' "$metadata_file")"

    if [ -z "$schema_version" ]; then
        _task_validation_log WARNING "metadata.json has no schema_version; using compatibility mode"
        return 0
    fi

    if [ "$schema_version" != "1" ]; then
        _task_validation_log ERROR "Unsupported zero-day task schema_version: $schema_version"
        return 1
    fi

    python3 - "$ROOT_DIR/zero_day_task_bundle_schema.json" "$metadata_file" <<'PY'
import json
import sys
from jsonschema import validate

schema_path, metadata_path = sys.argv[1:3]
with open(schema_path, 'r', encoding='utf-8') as f:
    schema = json.load(f)
with open(metadata_path, 'r', encoding='utf-8') as f:
    metadata = json.load(f)
validate(instance=metadata, schema=schema)
PY
}

zero_day_task_validate_source_dir() {
    local task_dir="$1"
    local req_file
    for req_file in "metadata.json" "fix.patch" "exploit_files/exploit.sh" "verify_files/verify_exploit.sh"; do
        if [ ! -f "$task_dir/$req_file" ]; then
            _task_validation_log ERROR "Required task file not found: $task_dir/$req_file"
            return 1
        fi
    done

    if find "$task_dir" -type d \( -name 'agent_output' -o -name '__pycache__' -o -name '.pytest_cache' -o -name 'build' -o -name 'dist' \) -print -quit | grep -q .; then
        _task_validation_log ERROR "Task directory contains generated runtime artifacts; zero-day tasks must stay source-only"
        return 1
    fi

    return 0
}

zero_day_task_resolve_metadata() {
    local task_dir="$1"
    local app_dir="$2"
    local source_task_dir="$3"

    ZERO_DAY_TASK_METADATA="$task_dir/metadata.json"
    zero_day_task_validate_metadata_schema_if_present "$ZERO_DAY_TASK_METADATA" || return 1

    if ! jq -e '.schema_version' "$ZERO_DAY_TASK_METADATA" >/dev/null 2>&1; then
        _task_validation_log WARNING "Task metadata has no schema_version; using older-field compatibility"
    fi

    ZERO_DAY_TASK_ID="$(jq -r '.task_id // .task_slug // empty' "$ZERO_DAY_TASK_METADATA")"
    if [ -z "$ZERO_DAY_TASK_ID" ] || [ "$ZERO_DAY_TASK_ID" = "null" ]; then
        ZERO_DAY_TASK_ID="$(basename "$source_task_dir")"
    fi

    ZERO_DAY_PACKAGE_NAME="$(jq -r '.runtime.package_name // .app_metadata_overrides.package_name // empty' "$ZERO_DAY_TASK_METADATA")"
    if [ -z "$ZERO_DAY_PACKAGE_NAME" ] || [ "$ZERO_DAY_PACKAGE_NAME" = "null" ]; then
        ZERO_DAY_PACKAGE_NAME="$(jq -r '.package_name // empty' "$app_dir/metadata.json")"
    fi
    if [ -z "$ZERO_DAY_PACKAGE_NAME" ] || [ "$ZERO_DAY_PACKAGE_NAME" = "null" ]; then
        _task_validation_log ERROR "Could not resolve package_name from task metadata or app metadata"
        return 1
    fi

    ZERO_DAY_BASELINE_COMMIT="$(jq -r '.baseline.commit // empty' "$ZERO_DAY_TASK_METADATA")"
    if [ -z "$ZERO_DAY_BASELINE_COMMIT" ] || [ "$ZERO_DAY_BASELINE_COMMIT" = "null" ]; then
        ZERO_DAY_BASELINE_COMMIT="$(jq -r '.commit_version // empty' "$app_dir/metadata.json")"
        if [ -n "$ZERO_DAY_BASELINE_COMMIT" ]; then
            _task_validation_log WARNING "metadata.json has no baseline.commit; falling back to app metadata commit_version"
        fi
    fi
    if [ -z "$ZERO_DAY_BASELINE_COMMIT" ] || [ "$ZERO_DAY_BASELINE_COMMIT" = "null" ]; then
        _task_validation_log ERROR "Could not resolve baseline commit"
        return 1
    fi

    ZERO_DAY_SECURE_PATCH_ABS="$task_dir/fix.patch"
    if [ ! -f "$ZERO_DAY_SECURE_PATCH_ABS" ]; then
        _task_validation_log ERROR "Secure comparator patch not found: $ZERO_DAY_SECURE_PATCH_ABS"
        return 1
    fi

    local secure_patch_rel
    secure_patch_rel="$(jq -r '.build.comparators.secure.patch // empty' "$ZERO_DAY_TASK_METADATA")"
    if [ -n "$secure_patch_rel" ] && [ "$secure_patch_rel" != "null" ] && [ "$secure_patch_rel" != "fix.patch" ]; then
        _task_validation_log ERROR "If build.comparators.secure.patch is set, it must be fix.patch"
        return 1
    fi

    local vulnerable_patch_rel
    vulnerable_patch_rel="$(jq -r '.build.comparators.vulnerable.patch // empty' "$ZERO_DAY_TASK_METADATA")"
    if [ -n "$vulnerable_patch_rel" ] && [ "$vulnerable_patch_rel" != "null" ]; then
        _task_validation_log ERROR "Zero-day tasks must use the unpatched baseline as the vulnerable comparator"
        return 1
    fi

    ZERO_DAY_BUILD_ENV_ARGS=()
    while IFS=$'\t' read -r key value; do
        [ -n "$key" ] || continue
        ZERO_DAY_BUILD_ENV_ARGS+=("$key=$value")
    done < <(
        jq -r '(.build.env // .build_env // {}) | to_entries[]? | [.key, (.value | tostring)] | @tsv' \
            "$ZERO_DAY_TASK_METADATA"
    )

    return 0
}

zero_day_task_run_build() {
    local app_name="$1"
    shift
    if [ ${#ZERO_DAY_BUILD_ENV_ARGS[@]} -gt 0 ]; then
        env "${ZERO_DAY_BUILD_ENV_ARGS[@]}" "$ROOT_DIR/build_apk.sh" "$app_name" --commit "$ZERO_DAY_BASELINE_COMMIT" "$@"
    else
        "$ROOT_DIR/build_apk.sh" "$app_name" --commit "$ZERO_DAY_BASELINE_COMMIT" "$@"
    fi
}

zero_day_task_run_validation() {
    local app_name="$1"
    local task_dir="$2"
    local skip_build="${3:-false}"
    local artifacts_dir="${4:-}"
    local keep_workspace="${5:-false}"

    local app_dir="$ROOT_DIR/apps/$app_name"
    if [ ! -d "$app_dir" ]; then
        _task_validation_log ERROR "App directory not found: $app_dir"
        return 1
    fi

    local source_task_dir
    source_task_dir="$(zero_day_task_resolve_abs_dir "$task_dir")" || return 1
    zero_day_task_validate_source_dir "$source_task_dir" || return 1

    if [ -n "$artifacts_dir" ]; then
        mkdir -p "$artifacts_dir"
        artifacts_dir="$(cd "$artifacts_dir" && pwd)"
    fi

    mkdir -p "$ROOT_DIR/tmp"
    ZERO_DAY_WORKSPACE="$(mktemp -d "$ROOT_DIR/tmp/zero_day_task.${app_name}.XXXXXX")"
    ZERO_DAY_TASK_WORK_DIR="$ZERO_DAY_WORKSPACE/task"
    mkdir -p "$ZERO_DAY_TASK_WORK_DIR" "$ZERO_DAY_WORKSPACE/output" "$ZERO_DAY_WORKSPACE/logs"
    cp -R "$source_task_dir/." "$ZERO_DAY_TASK_WORK_DIR/"

    if ! zero_day_task_resolve_metadata "$ZERO_DAY_TASK_WORK_DIR" "$app_dir" "$source_task_dir"; then
        rm -rf "$ZERO_DAY_WORKSPACE"
        ZERO_DAY_WORKSPACE=""
        return 1
    fi

    if ! task_validation_resolve_android_serial; then
        rm -rf "$ZERO_DAY_WORKSPACE"
        ZERO_DAY_WORKSPACE=""
        return 1
    fi

    _task_validation_log INFO "=========================================="
    _task_validation_log INFO "Zero-Day Task Validation"
    _task_validation_log INFO "=========================================="
    _task_validation_log INFO "App:             $app_name"
    _task_validation_log INFO "Task dir:        $source_task_dir"
    _task_validation_log INFO "Task id:         $ZERO_DAY_TASK_ID"
    _task_validation_log INFO "Package:         $ZERO_DAY_PACKAGE_NAME"
    _task_validation_log INFO "Baseline commit: $ZERO_DAY_BASELINE_COMMIT"
    _task_validation_log INFO "Android serial:  ${ANDROID_SERIAL}"
    if [ ${#ZERO_DAY_BUILD_ENV_ARGS[@]} -gt 0 ]; then
        _task_validation_log INFO "Build env:       ${ZERO_DAY_BUILD_ENV_ARGS[*]}"
    fi
    if [ -n "$artifacts_dir" ]; then
        _task_validation_log INFO "Artifacts dir:   $artifacts_dir"
    fi
    if [ "$keep_workspace" = true ]; then
        _task_validation_log INFO "Workspace kept:  $ZERO_DAY_WORKSPACE"
    fi
    _task_validation_log INFO "=========================================="

    local build_manifest="$app_dir/apk/.zero_day_build_manifest.json"
    local expected_patch_hash
    expected_patch_hash="$(shasum -a 256 "$ZERO_DAY_SECURE_PATCH_ABS" | awk '{print $1}')"

    if [ "$skip_build" = true ]; then
        _task_validation_log INFO "BUILD PHASE: Skipped (--skip-build)"
        local secure_apk="$app_dir/apk/hardened/${app_name}.apk"
        local vulnerable_apk="$app_dir/apk/${app_name}.apk"
        if [ ! -f "$secure_apk" ] || [ ! -f "$vulnerable_apk" ]; then
            _task_validation_log ERROR "Missing expected APK(s) under $app_dir/apk/"
            [ "$keep_workspace" = true ] || rm -rf "$ZERO_DAY_WORKSPACE"
            return 1
        fi
        if [ ! -f "$build_manifest" ]; then
            _task_validation_log ERROR "--skip-build: no build manifest at $build_manifest; cannot verify APKs were built for this task. Re-run without --skip-build."
            [ "$keep_workspace" = true ] || rm -rf "$ZERO_DAY_WORKSPACE"
            return 1
        fi
        local manifest_commit manifest_patch_hash
        manifest_commit="$(jq -r '.baseline_commit' "$build_manifest")"
        manifest_patch_hash="$(jq -r '.fix_patch_sha256' "$build_manifest")"
        if [ "$manifest_commit" != "$ZERO_DAY_BASELINE_COMMIT" ] || [ "$manifest_patch_hash" != "$expected_patch_hash" ]; then
            _task_validation_log ERROR "--skip-build: existing APKs were built for a different baseline/patch (manifest commit=$manifest_commit, patch=$manifest_patch_hash). Re-run without --skip-build."
            [ "$keep_workspace" = true ] || rm -rf "$ZERO_DAY_WORKSPACE"
            return 1
        fi
        _task_validation_log INFO "Build manifest verified: APKs match this task's baseline and fix.patch"
    else
        _task_validation_log INFO "BUILD PHASE"
        cd "$ROOT_DIR"
        _task_validation_log INFO "Building secure APK (with task fix.patch)..."
        if ! zero_day_task_run_build "$app_name" --hardened-patch "$ZERO_DAY_SECURE_PATCH_ABS"; then
            [ "$keep_workspace" = true ] || rm -rf "$ZERO_DAY_WORKSPACE"
            return 1
        fi
        _task_validation_log INFO "Building vulnerable APK (unpatched baseline)..."
        if ! zero_day_task_run_build "$app_name"; then
            [ "$keep_workspace" = true ] || rm -rf "$ZERO_DAY_WORKSPACE"
            return 1
        fi
        _task_validation_log SUCCESS "Both APKs built successfully"
        printf '{"baseline_commit":"%s","fix_patch_sha256":"%s","task_id":"%s"}\n' \
            "$ZERO_DAY_BASELINE_COMMIT" "$expected_patch_hash" "$ZERO_DAY_TASK_ID" \
            > "$build_manifest"
    fi

    task_validation_set_context \
        "$ROOT_DIR" \
        "$app_dir" \
        "$ZERO_DAY_TASK_WORK_DIR" \
        "$ZERO_DAY_WORKSPACE/output" \
        "$ZERO_DAY_WORKSPACE/logs" \
        "$artifacts_dir" \
        "$ZERO_DAY_PACKAGE_NAME" \
        "$ZERO_DAY_TASK_ID" \
        "$ZERO_DAY_BASELINE_COMMIT" \
        "$ZERO_DAY_SECURE_PATCH_ABS" \
        "$ZERO_DAY_WORKSPACE" \
        "per_phase" \
        "false"

    local result=0

    _task_validation_log INFO "PHASE 1: Secure Build (should NOT be vulnerable)"
    if ! task_validation_run_phase "Secure build" "secure" "apk/hardened/${app_name}.apk" "false"; then
        result=1
    fi
    task_validation_cleanup_runtime
    if [ "$result" -ne 0 ]; then
        _task_validation_log ERROR "Phase 1 (secure build) FAILED"
        [ "$keep_workspace" = true ] || rm -rf "$ZERO_DAY_WORKSPACE"
        return 1
    fi
    _task_validation_log SUCCESS "Phase 1 PASSED: Secure build is NOT vulnerable"

    _task_validation_log INFO "PHASE 2: Vulnerable Build (should be vulnerable)"
    if ! task_validation_run_phase "Vulnerable build" "vulnerable" "" "true"; then
        result=1
    fi
    task_validation_cleanup_runtime
    if [ "$result" -ne 0 ]; then
        _task_validation_log ERROR "Phase 2 (vulnerable build) FAILED"
        [ "$keep_workspace" = true ] || rm -rf "$ZERO_DAY_WORKSPACE"
        return 1
    fi

    _task_validation_log SUCCESS "Phase 2 PASSED: Vulnerable build IS vulnerable"
    _task_validation_log SUCCESS "=========================================="
    _task_validation_log SUCCESS "Zero-day task validation PASSED for $ZERO_DAY_TASK_ID"
    _task_validation_log SUCCESS "=========================================="

    if [ "$keep_workspace" != true ]; then
        rm -rf "$ZERO_DAY_WORKSPACE"
    fi
    return 0
}
