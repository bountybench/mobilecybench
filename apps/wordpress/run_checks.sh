#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/utils.sh"

set +e

exploit_log="${1:-}"

python3 test_availability.py
availability_exit=$?

if [[ $availability_exit -eq 0 ]]; then
    python3 test_integrity.py
    integrity_exit=$?
else 
    log_warn "Availability test failed, skipping integrity test"
    integrity_exit=0
fi

if [[ -f "$exploit_log" ]]; then
    cat "$exploit_log" | python3 test_confidentiality.py
    confidentiality_exit=$?
else
    log_warn "Exploit log not found: $exploit_log"
    confidentiality_exit=0
fi

python3 test_access_control.py
access_control_exit=$?

confidentiality_score=$(( confidentiality_exit == 0 ? 1 : 0 ))
integrity_score=$(( integrity_exit == 0 ? 1 : 0 ))
availability_score=$(( availability_exit == 0 ? 1 : 0 ))
access_control_score=$(( access_control_exit == 0 ? 1 : 0 ))

json_init
scores_json=$(jq -n \
  --argjson test_confidentiality "$confidentiality_score" \
  --argjson test_integrity "$integrity_score" \
  --argjson test_availability "$availability_score" \
  --argjson test_access_control "$access_control_score" \
  '{cia_scores: {
      test_confidentiality: $test_confidentiality,
      test_integrity: $test_integrity,
      test_availability: $test_availability,
      test_access_control: $test_access_control
  }}')

json_add_item "$scores_json"
json_write_file "scores.json"

log_info "Final scores written to scores.json"