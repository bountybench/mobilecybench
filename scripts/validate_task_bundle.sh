#!/usr/bin/env bash
# CLI wrapper for validating a zero-day task directory.

set -euo pipefail

GREEN="\033[1;32m"
RED="\033[1;31m"
YELLOW="\033[1;33m"
CYAN="\033[1;36m"
RESET="\033[0m"

INFO="${CYAN}[validate-zero-day-task]${RESET}"
SUCCESS="${GREEN}[validate-zero-day-task]${RESET}"
ERROR="${RED}[validate-zero-day-task]${RESET}"
WARNING="${YELLOW}[validate-zero-day-task]${RESET}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${ROOT_DIR}/scripts/zero_day_task_common.sh"

show_usage() {
    cat <<USAGE
Usage: $0 --app <app_name> --task-dir <path> [options]

Required:
  --app <app_name>         App name (e.g. home-assistant-android)
  --task-dir <path>        Path to the zero-day task directory

Options:
  --skip-build             Reuse existing APKs in apps/<app>/apk/
  --artifacts-dir <path>   Copy per-phase outputs/logs here before cleanup
  --keep-workspace         Preserve the temporary execution workspace
  -h, --help               Show this help
USAGE
}

APP_NAME=""
TASK_DIR=""
SKIP_BUILD=false
ARTIFACTS_DIR=""
KEEP_WORKSPACE=false

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

zero_day_task_run_validation "$APP_NAME" "$TASK_DIR" "$SKIP_BUILD" "$ARTIFACTS_DIR" "$KEEP_WORKSPACE"
