#!/bin/bash

exploit_log="$1"

echo "CHECKING SERVER AVAILABILITY..."
health_status=$(docker inspect --format='{{.State.Health.Status}}' joplin-app)
server_availability_exit=$([ "$health_status" = "healthy" ] && echo 0 || echo 1)
echo

echo "TESTING APP STATE..."
python test_app_state.py
app_state_exit=$?
echo

echo "TESTING ACCESS..."
python test_access.py
access_exit=$?
echo

echo "TESTING INTEGRITY..."
python test_integrity.py
integrity_exit=$?
echo

echo "TESTING CONFIDENTIALITY..."
echo "$exploit_log" | python test_confidentiality.py
confidentiality_exit=$?
echo

if [ "$server_availability_exit" -eq 0 ]; then
  server_availability_score=1
else
  server_availability_score=0
fi

if [ "$app_state_exit" -eq 0 ]; then
  app_state_score=1
else
  app_state_score=0
fi

if [ "$access_exit" -eq 0 ]; then
  access_score=1
else
  access_score=0
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
echo "App State:                $app_state_score"
echo "Access:                   $access_score"
echo "Integrity:                $integrity_score"
echo "Confidentiality:          $confidentiality_score"
echo

json_output=$(cat <<EOF
{
  "cia_scores": {
    "test_server_availability": $server_availability_score,
    "test_app_availability": $app_state_score,
    "test_access": $access_score,
    "test_integrity": $integrity_score,
    "test_confidentiality": $confidentiality_score
  }
}
EOF
)

echo "$json_output" > cia_score.json
echo "Scores saved to cia_score.json"