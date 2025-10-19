#!/bin/bash

# Universal run_checks.sh to run the four probe scripts for an app
app_path="$1"
exploit_log="$2"

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

if [ -d $app_path ]; then
  echo "cd into app directory..."
  cd $app_path
else
  echo "ERROR: app directory not found"
  exit 1
fi

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

echo "TESTING CONFIDENTIALITY..."
if [ -z "$exploit_log" ]; then
    echo "[FAIL] No log provided."
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

echo "$json_output" | jq . > /dev/null || echo "Final JSON for scores is invalid!"
echo "$json_output" > $app_path/scores.json
echo "Scores saved to $app_path/scores.json"

# Run generic checks
echo "App-specific checks were successfully run. Now running generic checks..."

echo "TESTING GENERIC AVAILABILITY..."
{
    gen_availability_output=$($PYTHON ../../evaluation/generic_probes/test_availability.py | tail -1)
    gen_availability_exit=$?
}
gen_availability_output=${gen_availability_output:-"{}"}
echo

echo "TESTING GENERIC CONFIDENTIALITY..."
if [ -z "$exploit_log" ]; then
    echo "[FAIL] No log provided."
    gen_confidentiality_exit=0
    gen_confidentiality_output='{"score": 0, "status": "no_log"}'
else
    {
        gen_confidentiality_output=$($PYTHON ../../evaluation/generic_probes/test_confidentiality.py "$exploit_log" | tail -1)
        gen_confidentiality_exit=$?
    }
    gen_confidentiality_output=${gen_confidentiality_output:-"{}"}
fi
echo

if [ "$gen_availability_exit" -ne 0 ] || [ -z "$gen_availability_output" ]; then
  echo "ERROR: Availability test failed to execute or produce output"
  exit 1
else
  gen_availability_score=$(echo "$gen_availability_output" | jq -r '.score // 0' 2>/dev/null || echo "0")
fi

if [ "$gen_confidentiality_exit" -ne 0 ] || [ -z "$gen_confidentiality_output" ]; then
  echo "ERROR: Confidentiality test failed to execute or produce output"
  exit 1
else
  gen_confidentiality_score=$(echo "$gen_confidentiality_output" | jq -r '.score // 0' 2>/dev/null || echo "0")
fi

echo
echo "FINAL SCORES:"
echo "Availability (Generic Probe):             $gen_availability_score"
echo "Confidentiality (Generic Probe):          $gen_confidentiality_score"
echo

gen_json_output=$(cat <<EOF
{
  "scores": {
    "test_availability": $gen_availability_score,
    "test_confidentiality": $gen_confidentiality_score
  },
  "availability_details": $gen_availability_output,
  "confidentiality_details": $gen_confidentiality_output
}
EOF
)

echo "$gen_json_output" | jq . > /dev/null || echo "Final JSON for generic scores is invalid!"
echo "$gen_json_output" > "$app_path/generic_scores.json"
echo "Scores saved to $app_path/generic_scores.json"
