#!/bin/bash

# Script to run generic probe scripts for an apps
exploit_log="$1"
app_name="$2"
app_path="$3"

# Use python3 if available, otherwise use python
if command -v python3 &>/dev/null; then
    PYTHON=python3
else
    PYTHON=python
    if ! $PYTHON -c "import sys; exit(0 if sys.version_info >= (3,) else 1)" &>/dev/null; then
        echo "Error: Python 3 is required but $PYTHON is Python 2" >&2
        exit 1
    fi
fi

echo "TESTING GENERIC AVAILABILITY..."
{
    availability_output=$($PYTHON evaluation/generic_probes/test_availability.py "$app_name" | tail -1)
    availability_exit=$?
}
availability_output=${availability_output:-"{}"}
echo

echo $PWD

echo "TESTING CONFIDENTIALITY..."
if [ -z "$exploit_log" ]; then
    echo "[PASS] No log provided."
    confidentiality_exit=0
    confidentiality_output='{"score": 0, "status": "no_log"}'
else
    {
        confidentiality_output=$($PYTHON evaluation/generic_probes/test_confidentiality.py "$app_name" "$exploit_log" | tail -1)
        confidentiality_exit=$?
    }
    confidentiality_output=${confidentiality_output:-"{}"}
fi
echo

# Standardized exit code handling: exit 0 = test executed successfully, read score from JSON
# Probes should never crash - if they do, it's an evaluator failure
if [ "$availability_exit" -ne 0 ] || [ -z "$availability_output" ]; then
  echo "ERROR: Availability test failed to execute or produce output"
  exit 1
else
  availability_score=$(echo "$availability_output" | jq -r '.score // 0' 2>/dev/null || echo "0")
fi

if [ "$confidentiality_exit" -ne 0 ] || [ -z "$confidentiality_output" ]; then
  echo "ERROR: Confidentiality test failed to execute or produce output"
  exit 1
else
  confidentiality_score=$(echo "$confidentiality_output" | jq -r '.score // 0' 2>/dev/null || echo "0")
fi

echo
echo "FINAL SCORES:"
echo "Availability:             $availability_score"
echo "Confidentiality:          $confidentiality_score"
echo

# Standardized JSON schema
json_output=$(cat <<EOF
{
  "scores": {
    "test_availability": $availability_score,
    "test_confidentiality": $confidentiality_score
  },
  "availability_details": $availability_output,
  "confidentiality_details": $confidentiality_output
}
EOF
)

echo "$json_output" | jq . > /dev/null || echo "Final JSON is invalid!"
echo "$json_output" > "$app_path/generic_scores.json"
echo "Scores saved to $app_path/generic_scores.json"
