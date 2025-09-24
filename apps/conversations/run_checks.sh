#!/bin/bash

exploit_log="$1"

echo "TESTING CONFIDENTIALITY..."
if [ -z "$exploit_log" ]; then
    echo "[PASS] No log provided."
    confidentiality_output=$(echo "" | python test_confidentiality.py 2>/dev/null)
else
    confidentiality_output=$(python test_confidentiality.py < "$exploit_log" 2>/dev/null)
fi

if [ $? -ne 0 ] || [ -z "$confidentiality_output" ]; then
    echo "ERROR: Confidentiality test failed to execute or produce output"
    exit 1
else
    confidentiality_score=$(echo "$confidentiality_output" | jq -r '.score // 0' 2>/dev/null || echo "0")
fi
echo

echo "TESTING INTEGRITY..."
integrity_output=$(python test_integrity.py 2>/dev/null)
if [ $? -ne 0 ] || [ -z "$integrity_output" ]; then
    echo "ERROR: Integrity test failed to execute or produce output"
    exit 1
else
    integrity_score=$(echo "$integrity_output" | jq -r '.score // 0' 2>/dev/null || echo "0")
fi
echo

echo "TESTING AVAILABILITY..."
availability_output=$(python test_availability.py 2>/dev/null)
if [ $? -ne 0 ] || [ -z "$availability_output" ]; then
    echo "ERROR: Availability test failed to execute or produce output"
    exit 1
else
    availability_score=$(echo "$availability_output" | jq -r '.score // 0' 2>/dev/null || echo "0")
fi
echo

echo "TESTING ACCESS CONTROL..."
access_output=$(python test_access_control.py 2>/dev/null)
if [ $? -ne 0 ] || [ -z "$access_output" ]; then
    echo "ERROR: Access control test failed to execute or produce output"
    exit 1
else
    access_score=$(echo "$access_output" | jq -r '.score // 0' 2>/dev/null || echo "0")
fi
echo

echo
echo "FINAL SCORES:"
echo "Confidentiality:          $confidentiality_score"
echo "Integrity:                $integrity_score"
echo "Availability:             $availability_score"
echo "Access:                   $access_score"
echo

json_output=$(cat <<EOF
{
  "scores": {
    "test_confidentiality": $confidentiality_score,
    "test_integrity": $integrity_score,
    "test_availability": $availability_score,
    "test_access": $access_score
  },
  "confidentiality_details": $confidentiality_output,
  "integrity_details": $integrity_output,
  "availability_details": $availability_output,
  "access_details": $access_output
}
EOF
)

echo "$json_output" | jq . > /dev/null || echo "⚠️ Final JSON is invalid!"
echo "$json_output" > scores.json
echo "Scores saved to scores.json"