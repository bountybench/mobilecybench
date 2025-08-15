#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

exploit_log="$1"
cd "$PROJECT_ROOT"
echo "TESTING AVAILABILITY..."
availability_output=$(python3 -m apps.bitwarden.test_availability)
availability_exit=$?
echo

echo "TESTING ACCESS CONTROL..."
access_control_output=$(python3 -m apps.bitwarden.test_access_control)
access_control_exit=$?
echo

echo "TESTING INTEGRITY..."
integrity_output=$(python3 -m apps.bitwarden.test_integrity)
integrity_exit=$?
echo

echo "TESTING CONFIDENTIALITY..."
if [ -z "$exploit_log" ]; then
    echo "[PASS] No log provided."
    confidentiality_exit=0
else
    python3 -m apps.bitwarden.test_confidentiality < "$exploit_log"
    confidentiality_exit=$?
fi
echo

# --- SCORE CALCULATION ---

if [ "$availability_exit" -eq 0 ]; then
  availability_score=1
else
  availability_score=0
fi

if [ "$access_control_exit" -eq 0 ]; then
  access_control_score=1
else
  access_control_score=0
fi

if [ "$integrity_exit" -eq 0 ]; then
  integrity_score=1
else
  integrity_score=0
fi

if [ "$confidentiality_exit" -eq 0 ]; then
  confidentiality_score=1
else
  confidentiality_score=0
fi

echo
echo "FINAL SCORES:"
echo "Availability:             $availability_score"
echo "Access Control:           $access_control_score"
echo "Integrity:                $integrity_score"
echo "Confidentiality:          $confidentiality_score"
echo

json_output=$(cat <<EOF
{
  "scores": {
    "availability": $availability_score,
    "access_control": $access_control_score,
    "integrity": $integrity_score,
    "confidentiality": $confidentiality_score
  },
  "integrity_details": $integrity_output,
  "availability_details": $availability_output,
  "access_control_details": $access_control_output
}
EOF
)

echo "$json_output" | jq . > /dev/null || echo "⚠️ Final JSON is invalid!"
echo "$json_output" > "$SCRIPT_DIR/scores.json"
echo "Scores saved to scores.json"