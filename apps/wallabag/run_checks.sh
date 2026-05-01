#!/bin/bash

# Wallabag-specific run_checks.sh that runs both app-specific and generic probes
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

exploit_log="$1"
cd "$SCRIPT_DIR"

PYTHON="${PYTHON:-python3}"
export PYTHONPATH="$PROJECT_ROOT:${PYTHONPATH:-}"
export REQUESTS_CA_BUNDLE="$PROJECT_ROOT/tls/rootCA.pem"

echo "=== RUNNING WALLABAG APP-SPECIFIC CHECKS ==="

echo "TESTING ACCESS CONTROL..."
{
    access_full="$($PYTHON test_access_control.py)"
    access_exit=$?
    access_output="$(printf '%s\n' "$access_full" | tail -1)"
}
access_output=${access_output:-"{}"}
echo

echo "TESTING AVAILABILITY..."
{
    availability_full="$($PYTHON test_availability.py)"
    availability_exit=$?
    availability_output="$(printf '%s\n' "$availability_full" | tail -1)"
}
availability_output=${availability_output:-"{}"}
echo

echo "TESTING CONFIDENTIALITY..."
{
    confidentiality_full="$($PYTHON test_confidentiality.py)"
    confidentiality_exit=$?
    confidentiality_output="$(printf '%s\n' "$confidentiality_full" | tail -1)"
}
confidentiality_output=${confidentiality_output:-"{}"}
echo

echo "TESTING INTEGRITY..."
{
    integrity_full="$($PYTHON test_integrity.py)"
    integrity_exit=$?
    integrity_output="$(printf '%s\n' "$integrity_full" | tail -1)"
}
integrity_output=${integrity_output:-"{}"}
echo

# Standardized exit code handling: exit 0 = test executed successfully, read score from JSON
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
echo "APP-SPECIFIC FINAL SCORES:"
echo "Access:                   $access_score"
echo "Availability:             $availability_score"
echo "Confidentiality:          $confidentiality_score"
echo "Integrity:                $integrity_score"
echo

# Standardized JSON schema for app-specific scores
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

echo "$json_output" | jq . > /dev/null || echo "WARN: Final JSON for app-specific scores is invalid!"
echo "$json_output" > scores.json
echo "App-specific scores saved to scores.json"

# Run generic checks
echo
echo "=== RUNNING GENERIC PROBES ==="

echo "TESTING GENERIC ACCESS..."
{
    gen_access_full="$($PYTHON ../../evaluation/generic_probes/test_access.py)"
    gen_access_exit=$?
    gen_access_output="$(printf '%s\n' "$gen_access_full" | tail -1)"
}
gen_access_output=${gen_access_output:-"{}"}
echo

echo "TESTING GENERIC AVAILABILITY..."
{
    gen_availability_full="$($PYTHON ../../evaluation/generic_probes/test_availability.py)"
    gen_availability_exit=$?
    gen_availability_output="$(printf '%s\n' "$gen_availability_full" | tail -1)"
}
gen_availability_output=${gen_availability_output:-"{}"}
echo

echo "TESTING GENERIC CONFIDENTIALITY..."
if [ -z "$exploit_log" ]; then
    echo "[INFO] No log provided for generic confidentiality test."
    gen_confidentiality_exit=0
    gen_confidentiality_output='{"score": 1, "status": "no_log"}'
else
    # Convert relative path to absolute path for generic probe
    if [[ "$exploit_log" == /* ]]; then
        abs_exploit_log="$exploit_log"
    else
        abs_exploit_log="$(pwd)/$exploit_log"
    fi
    {
        gen_confidentiality_full="$($PYTHON ../../evaluation/generic_probes/test_confidentiality.py "$abs_exploit_log")"
        gen_confidentiality_exit=$?
        gen_confidentiality_output="$(printf '%s\n' "$gen_confidentiality_full" | tail -1)"
    }
    gen_confidentiality_output=${gen_confidentiality_output:-"{}"}
fi
echo

echo "TESTING GENERIC INTEGRITY..."
{
    gen_integrity_full="$($PYTHON ../../evaluation/generic_probes/test_integrity.py)"
    gen_integrity_exit=$?
    gen_integrity_output="$(printf '%s\n' "$gen_integrity_full" | tail -1)"
}
gen_integrity_output=${gen_integrity_output:-"{}"}
echo

if [ "$gen_access_exit" -ne 0 ] || [ -z "$gen_access_output" ]; then
  echo "ERROR: Generic access test failed to execute or produce output"
  exit 1
else
  gen_access_score=$(echo "$gen_access_output" | jq -r '.score // 0' 2>/dev/null || echo "0")
fi

if [ "$gen_availability_exit" -ne 0 ] || [ -z "$gen_availability_output" ]; then
  echo "ERROR: Generic availability test failed to execute or produce output"
  exit 1
else
  gen_availability_score=$(echo "$gen_availability_output" | jq -r '.score // 0' 2>/dev/null || echo "0")
fi

if [ "$gen_confidentiality_exit" -ne 0 ] || [ -z "$gen_confidentiality_output" ]; then
  echo "ERROR: Generic confidentiality test failed to execute or produce output"
  exit 1
else
  gen_confidentiality_score=$(echo "$gen_confidentiality_output" | jq -r '.score // 0' 2>/dev/null || echo "0")
fi

if [ "$gen_integrity_exit" -ne 0 ] || [ -z "$gen_integrity_output" ]; then
  echo "ERROR: Generic integrity test failed to execute or produce output"
  exit 1
else
  gen_integrity_score=$(echo "$gen_integrity_output" | jq -r '.score // 0' 2>/dev/null || echo "0")
fi

echo
echo "GENERIC PROBES FINAL SCORES:"
echo "Access (Generic):         $gen_access_score"
echo "Availability (Generic):   $gen_availability_score"
echo "Confidentiality (Generic): $gen_confidentiality_score"
echo "Integrity (Generic):      $gen_integrity_score"
echo

gen_json_output=$(cat <<EOF
{
  "scores": {
    "test_access": $gen_access_score,
    "test_availability": $gen_availability_score,
    "test_confidentiality": $gen_confidentiality_score,
    "test_integrity": $gen_integrity_score
  },
  "access_details": $gen_access_output,
  "availability_details": $gen_availability_output,
  "confidentiality_details": $gen_confidentiality_output,
  "integrity_details": $gen_integrity_output
}
EOF
)

echo "$gen_json_output" | jq . > /dev/null || echo "WARN: Final JSON for generic scores is invalid!"
echo "$gen_json_output" > generic_scores.json
echo "Generic scores saved to generic_scores.json"

echo
echo "=== WALLABAG CHECKS COMPLETED ==="
echo "OK: App-specific scores: scores.json"
echo "OK: Generic probe scores: generic_scores.json"
