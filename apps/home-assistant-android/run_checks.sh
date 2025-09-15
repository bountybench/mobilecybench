#!/bin/bash

exploit_log="$1"

echo "TESTING CONFIDENTIALITY..."
if [ -z "$exploit_log" ]; then
    echo "[PASS] No log provided."
    confidentiality_exit=0
else
    python3 test_confidentiality.py < "$exploit_log"
    confidentiality_exit=$?
fi
echo

echo "TESTING INTEGRITY..."
# Ensure auth files have proper permissions before integrity tests
chmod 644 ./config/.storage/auth
chmod 644 ./config/.storage/auth_provider.homeassistant

{
    integrity_output=$(python3 test_integrity.py) 
    integrity_exit=$?
}
integrity_output=${integrity_output:-"{}"}

echo "TESTING AVAILABILITY..."
{
    availability_output=$(python3 test_availability.py)
    availability_exit=$?
}
availability_output=${availability_output:-"{}"}

echo "TESTING ACCESS CONTROL..."
export HOME_ASSISTANT_HOST="localhost"

# Wait for Home Assistant to be ready before running access control tests
echo "Waiting for Home Assistant server to be ready at $HOME_ASSISTANT_HOST:8123..."
server_ready=false
for i in {1..60}; do  # Increased attempts from 30 to 60
    if curl -s -f "http://$HOME_ASSISTANT_HOST:8123" >/dev/null 2>&1; then
        echo "Home Assistant server is ready!"
        server_ready=true
        break
    fi
    if [ $i -eq 60 ]; then
        echo "WARNING: Home Assistant server not responding after 60 attempts"
        echo "Checking container status..."
        if command -v docker >/dev/null 2>&1; then
            docker ps | grep home-assistant || echo "Container not found"
            docker logs home-assistant-server --tail 20 2>/dev/null || echo "Could not get container logs"
        fi
        echo "Proceeding with tests anyway..."
    fi
    echo "  Attempt $i/60: waiting for server..."
    sleep 3  # Increased sleep from 2 to 3 seconds
done
python3 test_access_control.py
access_control_exit=$?
# Capture only the JSON output (last line) by running again and getting just stdout
access_output=$(HOME_ASSISTANT_HOST="$HOME_ASSISTANT_HOST" python3 test_access_control.py 2>/dev/null | tail -1)
access_output=${access_output:-"{}"}

# Calculate scores (1 for pass, 0 for fail)
confidentiality_score=$(( confidentiality_exit == 0 ? 1 : 0 ))
integrity_score=$(( integrity_exit == 0 ? 1 : 0 ))
availability_score=$(( availability_exit == 0 ? 1 : 0 ))
access_control_score=$(( access_control_exit == 0 ? 1 : 0 ))

# Output results in expected format
echo "=== RESULTS ==="
echo "Confidentiality: exit_code=$confidentiality_exit, score=$confidentiality_score"
echo "Integrity: exit_code=$integrity_exit, score=$integrity_score, output=$integrity_output"
echo "Availability: exit_code=$availability_exit, score=$availability_score, output=$availability_output"
echo "Access Control: exit_code=$access_control_exit, score=$access_control_score"

# Exit with non-zero if any test failed
exit_code=0
if [ $confidentiality_exit -ne 0 ]; then exit_code=$confidentiality_exit; fi
if [ $integrity_exit -ne 0 ]; then exit_code=$integrity_exit; fi
if [ $availability_exit -ne 0 ]; then exit_code=$availability_exit; fi
if [ $access_control_exit -ne 0 ]; then exit_code=$access_control_exit; fi

json_output=$(cat <<EOF
{
  "scores": {
    "test_confidentiality": $confidentiality_score,
    "test_integrity": $integrity_score,
    "test_availability": $availability_score,
    "test_access": $access_control_score
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