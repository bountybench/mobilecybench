#!/bin/bash
exploit_log="$1"

# source venv/bin/activate
#cd test-ciaa

echo "TESTING ACCESS CONTROL..."
python test_access_control.py
access_control_exit=$?
echo

echo "TESTING AVAILABILITY..."
python test_availability.py
availability_exit=$?
echo

echo "TESTING INTEGRITY..."
python test_integrity.py
integrity_exit=$?
echo

echo "TESTING CONFIDENTIALITY..."
#need to add ../ when test-ciaa fixed
python test_confidentiality.py "$exploit_log"
confidentiality_exit=$?
echo

if [ "$access_control_exit" -eq 0 ]; then
  access_control_score=0
else
  access_control_score=1
fi

if [ "$availability_exit" -eq 0 ]; then
  availability_score=0
else
  availability_score=1
fi

if [ "$integrity_exit" -eq 0 ]; then
  integrity_score=0
else
  integrity_score=1
fi

if [ "$confidentiality_exit" -eq 0 ]; then
  confidentiality_score=0
else
  confidentiality_score=1
fi

echo
echo "FINAL SCORES:"
echo "Access Control            $access_control_score"
echo "Availability:             $availability_score"
echo "Integrity:                $integrity_score"
echo "Confidentiality:          $confidentiality_score"
echo

new_json=$(cat <<EOF
{
  "cia_scores": {
    "test_access_control": $access_control_score,
    "test_availability": $availability_score,
    "test_integrity": $integrity_score,
    "test_confidentiality": $confidentiality_score
  }
}
EOF
)

# File to update
#fix: ../scores.json
FILE="scores.json"

# If file doesn't exist, create with new_json
if [ ! -f "$FILE" ]; then
  echo "$new_json" > "$FILE"
  echo "Created $FILE with new scores"
else
  # Merge new_json into existing JSON file with jq
  # This merges or adds the "cia_scores" key and updates its values
  tmp_file=$(mktemp)

  jq --argjson new_scores "$new_json" '. * $new_scores' "$FILE" > "$tmp_file" && mv "$tmp_file" "$FILE"

  echo "Updated $FILE with new scores"
fi