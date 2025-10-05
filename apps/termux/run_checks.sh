#!/bin/bash

exploit_log="$1"

echo "TESTING ACCESS CONTROL..."
{
    access_output=$(python3 test_access_control.py)
    access_exit=$?
}
access_output=${access_output:-"{}"}
echo

echo "TESTING AVAILABILITY..."
{
    availability_output=$(python3 test_availability.py) 
    availability_exit=$?
}
availability_output=${availability_output:-"{}"}
echo

echo "TESTING CONFIDENTIALITY..."
if [ -z "$exploit_log" ]; then
    echo "[PASS] No log provided."
    confidentiality_exit=0
    confidentiality_output="{}"
else
    {
        confidentiality_output=$(python3 test_confidentiality.py "$exploit_log")
        confidentiality_exit=$?
    }
    confidentiality_output=${confidentiality_output:-"{}"}
fi
echo

echo "TESTING INTEGRITY..."
{
    integrity_output=$(python3 test_integrity.py) 
    integrity_exit=$?
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

# Full result (useful for logs)
full_json=$(cat <<EOF
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

# Write minimal scores.json matching expected format for diff
echo "{\n  \"scores\": {\n    \"test_confidentiality\": $confidentiality_score,\n    \"test_integrity\": $integrity_score,\n    \"test_availability\": $availability_score,\n    \"test_access\": $access_score\n  }\n}" > scores.json

# Also print the full JSON to stdout for debugging/log consumption
echo "$full_json"

