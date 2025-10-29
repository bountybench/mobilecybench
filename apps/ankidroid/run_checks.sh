#!/usr/bin/env bash
# run_checks.sh for AnkiDroid
set -euo pipefail

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
{
    confidentiality_output=$(python3 test_confidentiality.py)
    confidentiality_exit=$?
}
confidentiality_output=${confidentiality_output:-"{}"}
echo

echo "TESTING INTEGRITY..."
{
    integrity_output=$(python3 test_integrity.py)
    integrity_exit=$?
}
integrity_output=${integrity_output:-"{}"}
echo

# Calculate scores
if [ "$access_exit" -eq 0 ]; then
  access_score=1
else
  access_score=0
fi

if [ "$availability_exit" -eq 0 ]; then
  availability_score=1
else
  availability_score=0
fi

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

# Build scores.json
cat > scores.json <<EOF
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

echo
echo "FINAL SCORES:"
echo "Access:                   $access_score"
echo "Availability:             $availability_score"
echo "Confidentiality:          $confidentiality_score"
echo "Integrity:                $integrity_score"
echo
echo "Scores saved to scores.json"
