#!/usr/bin/env bash
set -euo pipefail
TOOL_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="/mobilecybench"
if [[ ! -f "/.dockerenv" ]]; then
    ROOT_DIR="$(git -C "$TOOL_SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null)"
fi
source "${ROOT_DIR}/utils/common.sh"

run_setup_submodules() {
  local candidates=( \
    "/usr/local/bin/setup_submodules.sh" \
    "/mobilecybench/tools/setup_submodules.sh" \
  )
  for p in "${candidates[@]}"; do
    if [ -x "$p" ]; then
      log_info "Running submodule setup script: $p"
      if ! "$p"; then
        log_warn "setup_submodules.sh returned non-zero (continuing startup)."
      fi
      return
    fi
  done
  log_warn "No setup_submodules.sh found in expected locations; skipping submodule sync."
}

main() {
  run_setup_submodules
  git config --global --add safe.directory /mobilecybench
  if [[ $# -gt 0 ]]; then
    log_info "Executing command: $*"
    exec "$@"
  else
    log_info "No command specified — starting persistent shell"
    exec /bin/bash -c "trap : TERM INT; sleep infinity & wait"
  fi
}

main "$@"
