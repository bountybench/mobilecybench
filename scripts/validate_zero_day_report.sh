#!/usr/bin/env bash
#
# validate_zero_day_report.sh
#
# Thin adapter for validating a zero-day task stored under an external
# report directory. Assumes the task lives at <report-dir>/task and then
# delegates all execution logic to validate_task_bundle.sh.

set -euo pipefail

show_usage() {
    cat <<USAGE
Usage: $0 --app <app_name> --report-dir <path> [options]

Required:
  --app <app_name>       App name (e.g. home-assistant-android)
  --report-dir <path>    Path to the report directory containing task/

Options:
  --skip-build           Reuse existing APKs in apps/<app>/apk/
  --artifacts-dir <dir>  Copy per-phase outputs/logs here before cleanup
  --keep-workspace       Preserve the temporary execution workspace
  -h, --help             Show this help
USAGE
}

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME=""
REPORT_DIR=""
declare -a FORWARD_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --app)
            APP_NAME="${2:-}"
            shift 2
            ;;
        --report-dir)
            REPORT_DIR="${2:-}"
            shift 2
            ;;
        --skip-build|--keep-workspace)
            FORWARD_ARGS+=("$1")
            shift
            ;;
        --artifacts-dir)
            FORWARD_ARGS+=("$1" "${2:-}")
            shift 2
            ;;
        -h|--help)
            show_usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            show_usage
            exit 1
            ;;
    esac
done

if [ -z "$APP_NAME" ] || [ -z "$REPORT_DIR" ]; then
    echo "--app and --report-dir are required" >&2
    show_usage
    exit 1
fi

if [ ! -d "$REPORT_DIR" ]; then
    echo "Report directory not found: $REPORT_DIR" >&2
    exit 1
fi

REPORT_DIR="$(cd "$REPORT_DIR" && pwd)"
TASK_DIR="$REPORT_DIR/task"

if [ ! -d "$TASK_DIR" ]; then
    echo "No task/ directory found under report: $REPORT_DIR" >&2
    exit 1
fi

exec "$ROOT_DIR/scripts/validate_task_bundle.sh" \
    --app "$APP_NAME" \
    --task-dir "$TASK_DIR" \
    "${FORWARD_ARGS[@]}"
