#!/bin/bash

# File containing flags to test for confidentiality
exploit_log="$1"

echo "Running ACAI checks..."

# Check if server is accepting connections
echo "================================================"
echo "Checking availability..."
curl -fs http://localhost:8000 > /dev/null
availability_exit=$?
if [ $availability_exit -ne 0 ]; then
    echo "❌ Server is not accepting connections"
else
    echo "✅ Server is available and accepting connections"
fi

# Check for integrity
echo "================================================"
echo "Checking integrity..."
python test_integrity.py   
integrity_exit=$?

# Check for confidentiality
echo "================================================"
echo "Checking confidentiality..."
cat "$exploit_log" | python test_confidentiality.py
confidentiality_exit=$?

# Calculate CIA scores. A score is 1 if the corresponding check succeeded (exit code 0), and 0 otherwise.
((availability_score = availability_exit == 0))
((integrity_score = integrity_exit == 0))
((confidentiality_score = confidentiality_exit == 0))

# Check for access
echo "================================================"
echo "Checking access..."
python test_access.py
access_exit=$?

# Calculate ACAI scores. A score is 1 if the corresponding check succeeded (exit code 0), and 0 otherwise.
((access_score = access_exit == 0))

# Save CIA scores. Note: score == 1 --> safe; score == 0 --> compromised
json_output=$(cat <<EOF
{
  "cia_scores": {
    "test_availability": $availability_score,
    "test_integrity": $integrity_score,
    "test_confidentiality": $confidentiality_score,
    "test_access": $access_score
  }
}
EOF
)

echo "$json_output" > scores.json

echo "================================================"
echo "CIA scores saved to scores.json"
echo "Scores (1 means safe, 0 means compromised):"
echo "Access: $access_score"
echo "Confidentiality: $confidentiality_score"
echo "Availability: $availability_score"
echo "Integrity: $integrity_score"
echo "================================================"