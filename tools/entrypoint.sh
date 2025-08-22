#!/usr/bin/env bash
set -euo pipefail
source "/mobilecybench/utils/common.sh"

run_setup_submodule() {
  local candidates=( \
    "/usr/local/bin/setup_submodule.sh" \
    "/mobilecybench/tools/setup_submodule.sh" \
  )
  for p in "${candidates[@]}"; do
    if [ -x "$p" ]; then
      log_info "Running submodule setup script: $p"
      if ! "$p"; then
        log_warn "setup_submodule.sh returned non-zero (continuing startup)."
      fi
      return
    fi
  done
  log_warn "No setup_submodule.sh found in expected locations; skipping submodule sync."
}

main() {
  run_setup_submodule
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
