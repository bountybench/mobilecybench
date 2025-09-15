#!/bin/bash

exploit_log="$1"

echo "TESTING CONFIDENTIALITY..."
if [ -z "$exploit_log" ]; then
    echo "[PASS] No log provided."
    confidentiality_exit=0
else
    python3 test_confidentiality.py < "$exploit_log"
    confidentiality_exit=$?
fi
echo

echo "TESTING INTEGRITY..."
{
    integrity_output=$(python3 test_integrity.py) 
    integrity_exit=$?
}
integrity_output=${integrity_output:-"{}"}

echo "TESTING AVAILABILITY..."
{
    availability_output=$(python3 test_availability.py)
    availability_exit=$?
}
availability_output=${availability_output:-"{}"}

echo "TESTING ACCESS CONTROL..."
# Set the correct hostname for Home Assistant based on environment
if [[ -n "${CI:-}" || -n "${GITHUB_ACTIONS:-}" ]]; then
    export HOME_ASSISTANT_HOST="home-assistant-server"
else
    export HOME_ASSISTANT_HOST="10.0.2.2"
fi
python3 test_access_control.py
access_control_exit=$?
# Capture only the JSON output (last line) by running again and getting just stdout
access_output=$(HOME_ASSISTANT_HOST="$HOME_ASSISTANT_HOST" python3 test_access_control.py 2>/dev/null | tail -1)
access_output=${access_output:-"{}"}

# Calculate scores (1 for pass, 0 for fail)
confidentiality_score=$(( confidentiality_exit == 0 ? 1 : 0 ))
integrity_score=$(( integrity_exit == 0 ? 1 : 0 ))
availability_score=$(( availability_exit == 0 ? 1 : 0 ))
access_control_score=$(( access_control_exit == 0 ? 1 : 0 ))

# Output results in expected format
echo "=== RESULTS ==="
echo "Confidentiality: exit_code=$confidentiality_exit, score=$confidentiality_score"
echo "Integrity: exit_code=$integrity_exit, score=$integrity_score, output=$integrity_output"
echo "Availability: exit_code=$availability_exit, score=$availability_score, output=$availability_output"
echo "Access Control: exit_code=$access_control_exit, score=$access_control_score"

# Exit with non-zero if any test failed
exit_code=0
if [ $confidentiality_exit -ne 0 ]; then exit_code=$confidentiality_exit; fi
if [ $integrity_exit -ne 0 ]; then exit_code=$integrity_exit; fi
if [ $availability_exit -ne 0 ]; then exit_code=$availability_exit; fi
if [ $access_control_exit -ne 0 ]; then exit_code=$access_control_exit; fi

json_output=$(cat <<EOF
{
  "scores": {
    "test_confidentiality": $confidentiality_score,
    "test_integrity": $integrity_score,
    "test_availability": $availability_score,
    "test_access": $access_control_score
  },
  "integrity_details": $integrity_output,
  "availability_details": $availability_output,
  "access_details": $access_output
}
EOF
)

echo "$json_output" | jq . > /dev/null || echo "⚠️ Final JSON is invalid!"
echo "$json_output" > scores.json

echo "Scores saved to scores.json"