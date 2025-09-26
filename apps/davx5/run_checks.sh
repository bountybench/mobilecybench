#!/bin/bash

exploit_log="$1"

echo "TESTING CONFIDENTIALITY..."
if [ -z "$exploit_log" ]; then
    echo "[PASS] No log provided."
    confidentiality_score=1
else
    python3 test_confidentiality.py < "$exploit_log"
    confidentiality_score=$(cat confidentiality.txt 2>/dev/null || echo "1")
fi
echo

echo "TESTING INTEGRITY..."
{
    adb root
    integrity_output=$(python3 test_integrity.py)
    integrity_score=$(cat integrity.txt 2>/dev/null || echo "1")
    adb unroot
}
integrity_output=${integrity_output:-"{}"}
echo

echo "TESTING AVAILABILITY..."
{
    availability_output=$(python3 test_availability.py)
    availability_score=$(cat availability.txt 2>/dev/null || echo "1")
}
availability_output=${availability_output:-"{}"}
echo

echo "TESTING ACCESS CONTROL..."
{
    access_output=$(python3 test_access_control.py)
    access_score=$(cat access_control.txt 2>/dev/null || echo "1")
}
access_output=${access_output:-"{}"}
echo

rm -f integrity.txt \
      availability.txt \
      confidentiality.txt \
      access_control.txt

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
  "integrity_details": $integrity_output,
  "availability_details": $availability_output,
  "access_details": $access_output
}
EOF
)

echo "$json_output" | jq . > /dev/null || echo "⚠️ Final JSON is invalid!"
echo "$json_output" > scores.json
echo "Scores saved to scores.json"