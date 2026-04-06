#!/usr/bin/env bash
#
# validate_task_bundle.sh
#
# Canonical validator for zero-day task bundles. A task bundle is an atomic,
# self-contained benchmark unit that can live either in the public app tree or
# in an external report directory. This script validates and executes the
# bundle without depending on its source checkout location.

set -euo pipefail

GREEN="\033[1;32m"
RED="\033[1;31m"
YELLOW="\033[1;33m"
CYAN="\033[1;36m"
RESET="\033[0m"

INFO="${CYAN}[validate-task-bundle]${RESET}"
SUCCESS="${GREEN}[validate-task-bundle]${RESET}"
ERROR="${RED}[validate-task-bundle]${RESET}"
WARNING="${YELLOW}[validate-task-bundle]${RESET}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME=""
TASK_DIR=""
APP_DIR=""
SKIP_BUILD=false
ARTIFACTS_DIR=""
KEEP_WORKSPACE=false

WORKSPACE=""
TASK_WORK_DIR=""
TASK_METADATA=""
TASK_ID=""
PACKAGE_NAME=""
BASELINE_COMMIT=""
SECURE_PATCH_REL=""
SECURE_PATCH_ABS=""
declare -a BUILD_ENV_ARGS=()

show_usage() {
    cat <<USAGE
Usage: $0 --app <app_name> --task-dir <path> [options]

Required:
  --app <app_name>         App name (e.g. home-assistant-android)
  --task-dir <path>        Path to the zero-day task bundle directory

Options:
  --skip-build             Reuse existing APKs in apps/<app>/apk/
  --artifacts-dir <path>   Copy per-phase outputs/logs here before cleanup
  --keep-workspace         Preserve the temporary execution workspace
  -h, --help               Show this help
USAGE
}

resolve_abs_dir() {
    local dir="$1"
    if [ ! -d "$dir" ]; then
        echo -e "${ERROR} Directory not found: $dir" >&2
        exit 1
    fi
    (
        cd "$dir" >/dev/null 2>&1 || exit 1
        pwd
    )
}

validate_metadata_schema_if_present() {
    local metadata_file="$1"
    local schema_version
    schema_version="$(jq -r '.schema_version // empty' "$metadata_file")"

    if [ -z "$schema_version" ]; then
        echo -e "${WARNING} metadata.json has no schema_version; using legacy compatibility mode"
        return 0
    fi

    if [ "$schema_version" != "1" ]; then
        echo -e "${ERROR} Unsupported task bundle schema_version: $schema_version"
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

resolve_task_metadata() {
    TASK_METADATA="$TASK_WORK_DIR/metadata.json"

    validate_metadata_schema_if_present "$TASK_METADATA"

    # Detect whether this is the canonical schema (has schema_version) or legacy
    if ! jq -e '.schema_version' "$TASK_METADATA" >/dev/null 2>&1; then
        echo -e "${WARNING} Task metadata uses legacy format (no schema_version)"
        echo -e "${WARNING} Migrate to the canonical schema — see documentation/ZERO_DAY_CI_INTERFACE.md"
    fi

    # --- task_id ---
    # Canonical: .task_id  |  Legacy: .task_slug
    TASK_ID="$(jq -r '.task_id // .task_slug // empty' "$TASK_METADATA")"
    if [ -z "$TASK_ID" ] || [ "$TASK_ID" = "null" ]; then
        TASK_ID="$(basename "$TASK_DIR")"
    fi

    # --- package_name ---
    # Canonical: .runtime.package_name  |  Legacy: .app_metadata_overrides.package_name
    PACKAGE_NAME="$(jq -r '.runtime.package_name // .app_metadata_overrides.package_name // empty' "$TASK_METADATA")"
    if [ -z "$PACKAGE_NAME" ] || [ "$PACKAGE_NAME" = "null" ]; then
        PACKAGE_NAME="$(jq -r '.package_name // empty' "$APP_DIR/metadata.json")"
    fi
    if [ -z "$PACKAGE_NAME" ] || [ "$PACKAGE_NAME" = "null" ]; then
        echo -e "${ERROR} Could not resolve package_name from task metadata or app metadata"
        return 1
    fi

    # --- baseline commit ---
    # Canonical: .baseline.commit  |  Legacy: app metadata .commit_version
    BASELINE_COMMIT="$(jq -r '.baseline.commit // empty' "$TASK_METADATA")"
    if [ -z "$BASELINE_COMMIT" ] || [ "$BASELINE_COMMIT" = "null" ]; then
        BASELINE_COMMIT="$(jq -r '.commit_version // empty' "$APP_DIR/metadata.json")"
        if [ -n "$BASELINE_COMMIT" ]; then
            echo -e "${WARNING} metadata.json has no baseline.commit; falling back to app metadata commit_version"
        fi
    fi
    if [ -z "$BASELINE_COMMIT" ] || [ "$BASELINE_COMMIT" = "null" ]; then
        echo -e "${ERROR} Could not resolve baseline commit"
        return 1
    fi

    # --- secure comparator patch ---
    # Canonical: .build.comparators.secure.patch  |  Legacy: .clean_apk_mode == "security_patch"
    SECURE_PATCH_REL="$(jq -r '.build.comparators.secure.patch // empty' "$TASK_METADATA")"
    if [ -z "$SECURE_PATCH_REL" ] || [ "$SECURE_PATCH_REL" = "null" ]; then
        if jq -e '.clean_apk_mode == "security_patch"' "$TASK_METADATA" >/dev/null 2>&1; then
            SECURE_PATCH_REL="fix.patch"
        fi
    fi
    if [ -z "$SECURE_PATCH_REL" ]; then
        SECURE_PATCH_REL="fix.patch"
    fi

    if [ "$SECURE_PATCH_REL" != "fix.patch" ]; then
        echo -e "${ERROR} Secure comparator patch must be task-local fix.patch (got: $SECURE_PATCH_REL)"
        return 1
    fi
    SECURE_PATCH_ABS="$TASK_WORK_DIR/$SECURE_PATCH_REL"
    if [ ! -f "$SECURE_PATCH_ABS" ]; then
        echo -e "${ERROR} Secure comparator patch not found: $SECURE_PATCH_ABS"
        return 1
    fi

    # --- vulnerable comparator ---
    # Must be null / absent for zero-day tasks (baseline as-is is vulnerable)
    local vulnerable_patch_rel
    vulnerable_patch_rel="$(jq -r '.build.comparators.vulnerable.patch // empty' "$TASK_METADATA")"
    if [ -n "$vulnerable_patch_rel" ] && [ "$vulnerable_patch_rel" != "null" ]; then
        echo -e "${ERROR} Zero-day task bundles must use the unpatched baseline as the vulnerable comparator"
        return 1
    fi

    # --- build env ---
    # Canonical: .build.env  |  Legacy: .build_env
    BUILD_ENV_ARGS=()
    while IFS=$'\t' read -r key value; do
        [ -n "$key" ] || continue
        BUILD_ENV_ARGS+=("$key=$value")
    done < <(
        jq -r '(.build.env // .build_env // {}) | to_entries[]? | [.key, (.value | tostring)] | @tsv' \
            "$TASK_METADATA"
    )
}

run_build() {
    if [ ${#BUILD_ENV_ARGS[@]} -gt 0 ]; then
        env "${BUILD_ENV_ARGS[@]}" "$ROOT_DIR/build_apk.sh" "$APP_NAME" --commit "$BASELINE_COMMIT" "$@"
    else
        "$ROOT_DIR/build_apk.sh" "$APP_NAME" --commit "$BASELINE_COMMIT" "$@"
    fi
}

resolve_android_serial() {
    if [ -n "${ANDROID_SERIAL:-}" ]; then
        echo -e "${INFO} Using ANDROID_SERIAL from environment: $ANDROID_SERIAL"
        return 0
    fi

    local -a devices=()
    while IFS= read -r device; do
        [ -n "$device" ] || continue
        devices+=("$device")
    done < <(adb devices | awk '$2 == "device" { print $1 }')

    if [ ${#devices[@]} -eq 0 ]; then
        echo -e "${ERROR} No online adb device found"
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
        echo -e "${WARNING} Multiple adb devices detected (${devices[*]}); using $ANDROID_SERIAL"
        return 0
    fi

    export ANDROID_SERIAL="${devices[0]}"
    echo -e "${INFO} Using adb device: $ANDROID_SERIAL"
}

uninstall_package() {
    if adb shell pm list packages 2>/dev/null | grep -q "^package:${PACKAGE_NAME}$"; then
        echo -e "${INFO} Uninstalling $PACKAGE_NAME..."
        adb uninstall "$PACKAGE_NAME" >/dev/null 2>&1 || true
    fi
}

copy_phase_artifacts() {
    local phase_slug="$1"
    if [ -z "$ARTIFACTS_DIR" ]; then
        return 0
    fi

    local phase_artifacts="$ARTIFACTS_DIR/$phase_slug"
    mkdir -p "$phase_artifacts"
    cp -R "$WORKSPACE/output/$phase_slug/." "$phase_artifacts/" 2>/dev/null || true
    cp -R "$WORKSPACE/logs/$phase_slug" "$phase_artifacts/logs" 2>/dev/null || true
    cp "$TASK_WORK_DIR/metadata.json" "$phase_artifacts/metadata.json" 2>/dev/null || true
    cp "$TASK_WORK_DIR/fix.patch" "$phase_artifacts/fix.patch" 2>/dev/null || true
}

cleanup_all() {
    set +e
    if [ -d "$APP_DIR" ] && [ -x "$APP_DIR/cleanup.sh" ]; then
        (
            cd "$APP_DIR" && ./cleanup.sh
        ) >/dev/null 2>&1 || true
    fi
    if [ -n "$PACKAGE_NAME" ]; then
        uninstall_package >/dev/null 2>&1 || true
    fi
    if [ -n "$WORKSPACE" ] && [ -d "$WORKSPACE" ] && [ "$KEEP_WORKSPACE" != true ]; then
        rm -rf "$WORKSPACE"
    fi
    set -e
}
trap cleanup_all EXIT

run_phase() {
    local phase_name="$1"
    local phase_slug="$2"
    local apk_arg="$3"
    local expect_vulnerable="$4"

    local phase_output="$WORKSPACE/output/$phase_slug"
    local phase_logs="$WORKSPACE/logs/$phase_slug"
    mkdir -p "$phase_output" "$phase_logs"

    echo -e "${INFO} === Phase: $phase_name (expect_vulnerable=$expect_vulnerable) ==="

    echo -e "${INFO} Installing APK..."
    cd "$APP_DIR"
    if [ -n "$apk_arg" ]; then
        ./start_runtime.sh --apk "$apk_arg" || {
            echo -e "${ERROR} start_runtime.sh failed"
            return 1
        }
    else
        ./start_runtime.sh || {
            echo -e "${ERROR} start_runtime.sh failed"
            return 1
        }
    fi

    if ! adb shell pm list packages 2>/dev/null | grep -q "^package:${PACKAGE_NAME}$"; then
        echo -e "${ERROR} Package $PACKAGE_NAME not installed after start_runtime.sh"
        return 1
    fi

    local -a task_env=(
        "ANDROID_SERIAL=${ANDROID_SERIAL:-}"
        "MCB_TASK_DIR=$TASK_WORK_DIR"
        "MCB_OUTPUT_DIR=$phase_output"
        "MCB_WORKSPACE_DIR=$WORKSPACE"
        "MCB_APP_DIR=$APP_DIR"
        "MCB_TASK_METADATA_JSON=$TASK_WORK_DIR/metadata.json"
        "MCB_APP_METADATA_JSON=$APP_DIR/metadata.json"
        "MCB_FIX_PATCH=$TASK_WORK_DIR/fix.patch"
        "MCB_PACKAGE_NAME=$PACKAGE_NAME"
        "MCB_TASK_ID=$TASK_ID"
        "MCB_BASELINE_COMMIT=$BASELINE_COMMIT"
        "MCB_PHASE=$phase_slug"
    )

    local prepare_hook="$TASK_WORK_DIR/prepare_app.sh"
    if [ -f "$prepare_hook" ]; then
        echo -e "${INFO} Running prepare_app.sh..."
        if ! (
            cd "$TASK_WORK_DIR" && \
            env "${task_env[@]}" timeout 300 bash "$prepare_hook" >"$phase_logs/prepare.log" 2>&1
        ); then
            cat "$phase_logs/prepare.log" >&2 || true
            echo -e "${ERROR} prepare_app.sh failed or timed out"
            copy_phase_artifacts "$phase_slug"
            return 1
        fi
        cat "$phase_logs/prepare.log" || true
        echo -e "${SUCCESS} prepare_app.sh completed"
    fi

    echo -e "${INFO} Running exploit in container..."
    if ! (
        cd "$TASK_WORK_DIR" && \
        env "${task_env[@]}" "$ROOT_DIR/utils/run_exploit_container.sh" \
            --exploit-dir "$TASK_WORK_DIR/exploit_files" \
            --output-dir "$phase_output" \
            --image "${EXPLOIT_IMAGE:-cybench/mobilecybench:latest}" \
            --utils-dir "$ROOT_DIR/utils" \
            --codebase-dir "$APP_DIR/codebase" \
            >"$phase_logs/exploit.log" 2>&1
    ); then
        cat "$phase_logs/exploit.log" || true
        echo -e "${WARNING} Exploit returned non-zero (may be expected)"
    else
        cat "$phase_logs/exploit.log" || true
    fi

    echo -e "${INFO} Running verification..."
    local verify_script="$TASK_WORK_DIR/verify_files/verify_exploit.sh"
    chmod +x "$verify_script"
    set +e
    (
        cd "$TASK_WORK_DIR" && env "${task_env[@]}" bash "$verify_script" >"$phase_logs/verify.log" 2>&1
    )
    local verify_exit=$?
    set -e
    cat "$phase_logs/verify.log" || true

    if [ "$verify_exit" -gt 1 ]; then
        echo -e "${ERROR} Verifier failed with unexpected exit code $verify_exit"
        copy_phase_artifacts "$phase_slug"
        return 1
    fi

    if [ "$expect_vulnerable" = "true" ]; then
        if [ "$verify_exit" -eq 0 ]; then
            echo -e "${SUCCESS} Vulnerable build IS vulnerable (as expected)"
        else
            echo -e "${ERROR} Vulnerable build is NOT vulnerable (expected exit 0, got $verify_exit)"
            copy_phase_artifacts "$phase_slug"
            return 1
        fi
    else
        if [ "$verify_exit" -eq 1 ]; then
            echo -e "${SUCCESS} Secure build is NOT vulnerable (as expected)"
        else
            echo -e "${ERROR} Secure build IS vulnerable (expected exit 1, got $verify_exit)"
            copy_phase_artifacts "$phase_slug"
            return 1
        fi
    fi

    copy_phase_artifacts "$phase_slug"
    return 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --app)
            APP_NAME="${2:-}"
            shift 2
            ;;
        --task-dir)
            TASK_DIR="${2:-}"
            shift 2
            ;;
        --skip-build)
            SKIP_BUILD=true
            shift
            ;;
        --artifacts-dir)
            ARTIFACTS_DIR="${2:-}"
            shift 2
            ;;
        --keep-workspace)
            KEEP_WORKSPACE=true
            shift
            ;;
        -h|--help)
            show_usage
            exit 0
            ;;
        *)
            echo -e "${ERROR} Unknown argument: $1"
            show_usage
            exit 1
            ;;
    esac
done

if [ -z "$APP_NAME" ] || [ -z "$TASK_DIR" ]; then
    echo -e "${ERROR} --app and --task-dir are required"
    show_usage
    exit 1
fi

APP_DIR="$ROOT_DIR/apps/$APP_NAME"
if [ ! -d "$APP_DIR" ]; then
    echo -e "${ERROR} App directory not found: $APP_DIR"
    exit 1
fi
TASK_DIR="$(resolve_abs_dir "$TASK_DIR")"

if [ -n "$ARTIFACTS_DIR" ]; then
    mkdir -p "$ARTIFACTS_DIR"
    ARTIFACTS_DIR="$(cd "$ARTIFACTS_DIR" && pwd)"
fi

for req_file in "metadata.json" "fix.patch" "exploit_files/exploit.sh" "verify_files/verify_exploit.sh"; do
    if [ ! -f "$TASK_DIR/$req_file" ]; then
        echo -e "${ERROR} Required task bundle file not found: $TASK_DIR/$req_file"
        exit 1
    fi
done

if find "$TASK_DIR" -type d \( -name 'agent_output' -o -name '__pycache__' -o -name '.pytest_cache' -o -name 'build' -o -name 'dist' \) -print -quit | grep -q .; then
    echo -e "${ERROR} Task bundle contains generated runtime artifacts; task bundles must be source-only"
    exit 1
fi

mkdir -p "$ROOT_DIR/tmp"
WORKSPACE="$(mktemp -d "$ROOT_DIR/tmp/zero_day_task_bundle.${APP_NAME}.XXXXXX")"
TASK_WORK_DIR="$WORKSPACE/task"
mkdir -p "$TASK_WORK_DIR" "$WORKSPACE/output" "$WORKSPACE/logs"
cp -R "$TASK_DIR/." "$TASK_WORK_DIR/"

resolve_task_metadata
resolve_android_serial

echo -e "${INFO} =========================================="
echo -e "${INFO} Zero-Day Task Bundle Validation"
echo -e "${INFO} =========================================="
echo -e "${INFO} App:            $APP_NAME"
echo -e "${INFO} Task bundle:    $TASK_DIR"
echo -e "${INFO} Task id:        $TASK_ID"
echo -e "${INFO} Package:        $PACKAGE_NAME"
echo -e "${INFO} Baseline commit: $BASELINE_COMMIT"
echo -e "${INFO} Android serial: ${ANDROID_SERIAL}"
if [ ${#BUILD_ENV_ARGS[@]} -gt 0 ]; then
    echo -e "${INFO} Build env:      ${BUILD_ENV_ARGS[*]}"
fi
if [ -n "$ARTIFACTS_DIR" ]; then
    echo -e "${INFO} Artifacts dir:  $ARTIFACTS_DIR"
fi
if [ "$KEEP_WORKSPACE" = true ]; then
    echo -e "${INFO} Workspace kept: $WORKSPACE"
fi
echo -e "${INFO} =========================================="

if [ "$SKIP_BUILD" = true ]; then
    echo -e "${INFO} BUILD PHASE: Skipped (--skip-build)"
    SECURE_APK="$APP_DIR/apk/hardened/${APP_NAME}.apk"
    VULNERABLE_APK="$APP_DIR/apk/${APP_NAME}.apk"
    if [ ! -f "$SECURE_APK" ] || [ ! -f "$VULNERABLE_APK" ]; then
        echo -e "${ERROR} Missing expected APK(s) under $APP_DIR/apk/"
        exit 1
    fi
else
    echo -e "${INFO} BUILD PHASE"
    cd "$ROOT_DIR"
    echo -e "${INFO} Building secure APK (with task fix.patch)..."
    run_build --hardened-patch "$SECURE_PATCH_ABS"
    echo -e "${INFO} Building vulnerable APK (unpatched baseline)..."
    run_build
    echo -e "${SUCCESS} Both APKs built successfully"
fi

echo -e "${INFO} PHASE 1: Secure Build (should NOT be vulnerable)"
if run_phase "Secure build" "secure" "apk/hardened/${APP_NAME}.apk" "false"; then
    phase1_result=0
else
    phase1_result=1
fi

cd "$APP_DIR"
./cleanup.sh 2>/dev/null || true
uninstall_package
if [ "$phase1_result" -ne 0 ]; then
    echo -e "${ERROR} Phase 1 (secure build) FAILED"
    exit 1
fi

echo -e "${SUCCESS} Phase 1 PASSED: Secure build is NOT vulnerable"

echo -e "${INFO} PHASE 2: Vulnerable Build (should be vulnerable)"
if run_phase "Vulnerable build" "vulnerable" "" "true"; then
    phase2_result=0
else
    phase2_result=1
fi

cd "$APP_DIR"
./cleanup.sh 2>/dev/null || true
uninstall_package
if [ "$phase2_result" -ne 0 ]; then
    echo -e "${ERROR} Phase 2 (vulnerable build) FAILED"
    exit 1
fi

echo -e "${SUCCESS} Phase 2 PASSED: Vulnerable build IS vulnerable"
echo -e "${SUCCESS} =========================================="
echo -e "${SUCCESS} Zero-day task bundle validation PASSED for $TASK_ID"
echo -e "${SUCCESS} =========================================="
