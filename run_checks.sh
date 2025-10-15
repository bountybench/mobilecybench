#!/bin/bash

# Universal run_checks.sh to run the four probe scripts for an app
app_path="$1"
exploit_log="$2"

# Use python3 if available, otherwise use python
if command -v python3 &>/dev/null; then
    PYTHON=python3
else
    PYTHON=python
fi

if [ -d $app_path ]; then
  echo "cd into app directory..."
  cd $app_path
else
  echo "ERROR: app directory not found"
  exit 1
fi

APP_NAME=$(basename "$(pwd)")

echo "TESTING ACCESS CONTROL..."
{
    access_output=$($PYTHON test_access_control.py | tail -1)
    access_exit=$?
}
access_output=${access_output:-"{}"}
echo

echo "TESTING AVAILABILITY..."
{
    availability_output=$($PYTHON test_availability.py | tail -1) 
    availability_exit=$?
}
availability_output=${availability_output:-"{}"}
echo

echo "TESTING AVAILABILITY (GENERIC)..."
{
    generic_availability_output=$($PYTHON ../../evaluation/generic_probes/test_availability.py "$APP_NAME") 
    generic_availability_exit=$?
}
generic_availability_output=${generic_availability_output:-"{}"}
echo

echo "TESTING CONFIDENTIALITY..."
if [ -z "$exploit_log" ]; then
    echo "[PASS] No log provided."
    confidentiality_exit=0
    confidentiality_output='{"score": 0, "status": "no_log"}'
else
    {
        confidentiality_output=$($PYTHON test_confidentiality.py "$exploit_log" | tail -1)
        confidentiality_exit=$?
    }
    confidentiality_output=${confidentiality_output:-"{}"}
fi
echo

echo "TESTING CONFIDENTIALITY (GENERIC)..."
{
    generic_confidentiality_output=$($PYTHON ../../evaluation/generic_probes/test_confidentiality.py "$exploit_log")
    generic_confidentiality_exit=$?
}
generic_confidentiality_output=${generic_confidentiality_output:-"{}"}
echo

echo "TESTING INTEGRITY..."
{
    integrity_output=$($PYTHON test_integrity.py | tail -1) 
    integrity_exit=$?
}
integrity_output=${integrity_output:-"{}"}
echo

# Standardized exit code handling: exit 0 = test executed successfully, read score from JSON
# Probes should never crash - if they do, it's an evaluator failure
if [ "$access_exit" -ne 0 ] || [ -z "$access_output" ]; then
  echo "ERROR: Access control test failed to execute or produce output"
  exit 1
else
  access_score=$(echo "$access_output" | jq -r '.score // 0' 2>/dev/null || echo "0")
fi

# Merge availability outputs (generic + specific, with specific taking priority)
if [ "$availability_exit" -ne 0 ] || [ -z "$availability_output" ]; then
  echo "ERROR: Availability test failed to execute or produce output"
  exit 1
elif [ "$generic_availability_exit" -ne 0 ] || [ -z "$generic_availability_output" ]; then
  echo "ERROR: Generic availability test failed to execute or produce output"
  exit 1
else
  merged_availability=$(jq -nc \
    --argjson generic "$generic_availability_output" \
    --argjson specific "$availability_output" \
    '$generic + $specific')
  availability_score=$(echo "$merged_availability" | jq -r '.score // 0' 2>/dev/null || echo "0")
  availability_output="$merged_availability"
fi

# Merge confidentiality outputs (generic + specific, with specific taking priority)
if [ "$confidentiality_exit" -ne 0 ] || [ -z "$confidentiality_output" ]; then
  echo "ERROR: Confidentiality test failed to execute or produce output"
  exit 1
elif [ "$generic_confidentiality_exit" -ne 0 ] || [ -z "$generic_confidentiality_output" ]; then
  echo "ERROR: Generic confidentiality test failed to execute or produce output"
  exit 1
else
  merged_confidentiality=$(jq -nc \
    --argjson generic "$generic_confidentiality_output" \
    --argjson specific "$confidentiality_output" \
    '$generic + $specific')
  confidentiality_score=$(echo "$merged_confidentiality" | jq -r '.score // 0' 2>/dev/null || echo "0")
  confidentiality_output="$merged_confidentiality"
fi

if [ "$integrity_exit" -ne 0 ] || [ -z "$integrity_output" ]; then
  echo "ERROR: Integrity test failed to execute or produce output"
  exit 1
else
  integrity_score=$(echo "$integrity_output" | jq -r '.score // 0' 2>/dev/null || echo "0")
fi

echo
echo "FINAL SCORES:"
echo "Access:                   $access_score"
echo "Availability:             $availability_score"
echo "Confidentiality:          $confidentiality_score"
echo "Integrity:                $integrity_score"
echo

# Standardized JSON schema
json_output=$(cat <<EOF
{
  "scores": {
    "test_access": $access_score,
    "test_availability": $availability_score,
    "test_confidentiality": $confidentiality_score,
    "test_integrity": $integrity_score
  },
  "access_details": $access_output,
  "availability_details": $availability_output,
  "confidentiality_details": $confidentiality_output,
  "integrity_details": $integrity_output
}
EOF
)

echo "$json_output" | jq . > /dev/null || echo "Final JSON is invalid!"
echo "$json_output" > scores.json
echo "Scores saved to scores.json"
