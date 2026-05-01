#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
source "$ROOT_DIR/utils/android.sh"
source "$SCRIPT_DIR/helpers/victim_state.sh"

main(){
  jerboa_restore_victim_state
  log_info "Jerboa victim/app state restored"
}

main "$@"
