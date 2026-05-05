#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${MCB_APP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
ROOT_DIR="$(cd "$APP_DIR/../.." && pwd)"
source "$ROOT_DIR/utils/android.sh"
source "$APP_DIR/helpers/victim_state.sh"

main(){
  log_info "Preparing Jerboa replay victim for attacker_model=${MCB_ATTACKER_MODEL:-unknown}"
  jerboa_restore_victim_state
  log_info "Jerboa replay victim state restored"
}

main "$@"
