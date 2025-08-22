#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="/mobilecybench"
if [[ ! -f "/.dockerenv" ]]; then
    ROOT_DIR="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null)"
fi
source "${ROOT_DIR}/utils/common.sh"

mark_safe_submodules() {
  local root="/mobilecybench"
  local git_entry repo_dir
  while IFS= read -r git_entry; do
    [[ -z "$git_entry" ]] && continue
    repo_dir=$(dirname "$git_entry")
    repo_dir=$(cd "$repo_dir" && pwd -P) || continue
    if ! git config --global --get-all safe.directory 2>/dev/null | grep -Fxq "$repo_dir"; then
      git config --global --add safe.directory "$repo_dir"
      log_info "Added git safe.directory: $repo_dir"
    fi
  done < <(find "$root" -name .git -print 2>/dev/null || true)
}

main() {
  log_info "Preparing to sync submodules"
  mark_safe_submodules
  log_info "Syncing submodules (using default Git transport)"
  git submodule sync --recursive
  if ! git submodule update --init --recursive --timeout=30; then
    log_warn "Retrying submodule update once"
    sleep 2
    git submodule update --init --recursive --timeout=30
  fi
  log_info "Submodules updated"
}

main "$@"
