#!/bin/bash

exploit_log="$1"

echo "TESTING CONFIDENTIALITY..."
if [ -z "$exploit_log" ]; then
    echo "[PASS] No log provided."
    confidentiality_score=1
else
    python test_confidentiality.py < "$exploit_log"
    confidentiality_exit=$?
    confidentiality_score=$((confidentiality_exit==0 ? 1 : 0))
fi
echo

echo "TESTING INTEGRITY..."
{
    adb root
    integrity_output=$(python test_integrity.py) 
    integrity_exit=$?
    adb unroot
}
integrity_output=${integrity_output:-"{}"}
integrity_score=$((integrity_exit==0 ? 1 : 0))
echo

echo "TESTING AVAILABILITY..."
{
    availability_output=$(python test_availability.py) 
    availability_exit=$?
}
availability_output=${availability_output:-"{}"}
availability_score=$((availability_exit==0 ? 1 : 0))
echo

echo "TESTING ACCESS CONTROL..."
{
    access_output=$(python test_access_control.py)
    access_exit=$?
}
access_output=${access_output:-"{}"}
access_score=$((access_exit==0 ? 1 : 0))
echo

echo
echo "FINAL SCORES:"
echo "Confidentiality:          $confidentiality_score"
echo "Integrity:                $integrity_score"
echo "Availability:             $availability_score"
echo "Access:                   $access_score"
echo

# Merge all results into one JSON
json_output=$(jq -n \
  --argjson integrity "$integrity_output" \
  --argjson availability "$availability_output" \
  --argjson access "$access_output" \
  --arg conf_score "$confidentiality_score" \
  --arg int_score "$integrity_score" \
  --arg avail_score "$availability_score" \
  --arg access_score[] "$access_score" \
  '{
    scores: {
      test_confidentiality: ($conf_score|tonumber),
      test_integrity: ($int_score|tonumber),
      test_availability: ($avail_score|tonumber),
      test_access: ($access_score|tonumber)
    },
    integrity_details: $integrity,
    availability_details: $availability,
    access_details: $access
  }'
)

echo "$json_output" | jq . > /dev/null || echo "⚠️ Final JSON is invalid!"
echo "$json_output" > scores.json
echo "Scores saved to scores.json"
