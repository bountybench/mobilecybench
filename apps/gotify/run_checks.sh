#!/bin/bash
exploit_log="$1"

# Source environment variables from .env file if it exists
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# Set APP_SERVER_URL for CI environment
export APP_SERVER_URL="http://10.0.2.2:8080"

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
else
    confidentiality_output=$(python3 test_confidentiality.py "$exploit_log")
    confidentiality_exit=$?
fi
confidentiality_output=${confidentiality_output:-"{}"}
echo

echo "TESTING INTEGRITY..."
{
    integrity_output=$(python3 test_integrity.py)
    integrity_exit=$?
}
integrity_output=${integrity_output:-"{}"}
echo

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

echo
echo "FINAL SCORES:"
echo "Access:               $access_score"
echo "Availability:         $availability_score"
echo "Confidentiality:      $confidentiality_score"
echo "Integrity:            $integrity_score"
echo

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

echo "$json_output" | python3 -m json.tool > /dev/null || echo "Final JSON is invalid!"
echo "$json_output" > scores.json
echo "Scores saved to scores.json"