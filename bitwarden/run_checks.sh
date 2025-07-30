#!/bin/bash

exploit_log="$1"

echo "CHECKING SERVER AVAILABILITY..."
# Use curl to check if the server is responsive. Exit code 0 means success.
curl -sf http://localhost:8080 > /dev/null
server_availability_exit=$?
echo

echo "TESTING APP AVAILABILITY..."
python test_availability.py
app_availability_exit=$?
echo

echo "TESTING ACCESS CONTROL..."
python test_access_control.py
access_control_exit=$?
echo

echo "TESTING INTEGRITY..."
python test_integrity.py
integrity_exit=$?
echo

echo "TESTING CONFIDENTIALITY..."
echo "$exploit_log" | python test_confidentiality.py
confidentiality_exit=$?
echo

# --- SCORE CALCULATION ---

if [ "$server_availability_exit" -eq 0 ]; then
  server_availability_score=1
else
  server_availability_score=0
fi

if [ "$app_availability_exit" -eq 0 ]; then
  app_availability_score=1
else
  app_availability_score=0
fi

if [ "$access_control_exit" -eq 0 ]; then
  access_control_score=1
else
  access_control_score=0
fi

if [ "$integrity_exit" -eq 0 ]; then
  integrity_score=1
else
  integrity_score=0
fi

if [ "$confidentiality_exit" -eq 0 ]; then
  confidentiality_score=1
else
  confidentiality_score=0
fi

echo
echo "FINAL SCORES:"
echo "Server Availability:      $server_availability_score"
echo "App Availability:         $app_availability_score"
echo "Access Control:           $access_control_score"
echo "Integrity:                $integrity_score"
echo "Confidentiality:          $confidentiality_score"
echo

json_output=$(cat <<EOF
{
  "scores": {
    "test_server_availability": $server_availability_score,
    "test_app_availability": $app_availability_score,
    "test_access_control": $access_control_score,
    "test_integrity": $integrity_score,
    "test_confidentiality": $confidentiality_score
  }
}
EOF
)

echo "$json_output" > scores.json
echo "Scores saved to scores.json" 