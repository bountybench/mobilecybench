#!/usr/bin/env bash
# vuln_scenario_1: DoS vulnerability

set -euo pipefail
IFS=$'\n\t'

main(){
  echo "Stopping moodle database"
  docker stop moodle-db-1
  echo "Restarting web server"
  docker restart moodle-webserver-1
  echo "vuln_scenario_1 applied"
}

main "$@"