#!/usr/bin/env bash
# vuln_scenario_1: DoS vulnerability

set -euo pipefail
IFS=$'\n\t'

log(){ printf '[vuln0] %s\n' "$*"; }

main(){
  docker stop moodle-db-1
}

main "$@"