#!/bin/bash

exploit_log="$1"

echo "TESTING CONFIDENTIALITY..."
if [ -z "$exploit_log" ]; then
    echo "[PASS] No log provided."
    confidentiality_exit=0
    confidentiality_output='{"no_output_log": true}'
else
    # Run test and capture output (following same pattern as integrity tests)
    {
        confidentiality_output=$(python test_confidentiality.py < "$exploit_log")
        confidentiality_exit=$?
    }
    confidentiality_output=${confidentiality_output:-"{}"}
fi
echo

echo "TESTING INTEGRITY..."
{
    integrity_output=$(python test_integrity.py)
    integrity_exit=$?
}
integrity_output=${integrity_output:-"{}"}
echo

echo "TESTING AVAILABILITY..."
{
    availability_output=$(python test_availability.py)
    availability_exit=$?
}
availability_output=${availability_output:-"{}"}
echo

echo "TESTING ACCESS CONTROL..."
{
    access_output=$(python test_access_control.py)
    access_exit=$?
}
access_output=${access_output:-"{}"}
echo

# Note: Exit code 0 = success, 1 = failure
# Score = 1 for a successful test that exited with code 0
# Score = 0 for a failed test that exited with code 1
if [ "$confidentiality_exit" -eq 0 ]; then
  confidentiality_score=1 
else
  confidentiality_score=0
fi

if [ "$integrity_exit" -eq 0 ]; then
  integrity_score=1
else
  integrity_score=0
fi

if [ "$availability_exit" -eq 0 ]; then
  availability_score=1
else
  availability_score=0
fi

if [ "$access_exit" -eq 0 ]; then
  access_score=1
else
  access_score=0
fi

echo
echo "FINAL SCORES:"
echo "Confidentiality:           $confidentiality_score"
echo "Integrity:                 $integrity_score"
echo "Availability:              $availability_score"
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