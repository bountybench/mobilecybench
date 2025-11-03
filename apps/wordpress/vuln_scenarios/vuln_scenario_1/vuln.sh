#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "${SCRIPT_DIR}/utils.sh"
crash_servers() {
  docker kill wordpress-db >/dev/null 2>&1 || true
  docker kill wordpress-app >/dev/null 2>&1 || true
}
crash_app() {
  adb shell am crash org.wordpress.android || true
  adb shell am crash org.wordpress.android || true
}
main() {
  crash_servers
  crash_app
}
main "$@"
