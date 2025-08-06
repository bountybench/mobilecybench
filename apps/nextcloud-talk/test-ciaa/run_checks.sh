#!/bin/bash
exploit_log="$1"

source venv/bin/activate
cd test-ciaa

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
python test_confidentiality.py "$exploit_log"
confidentiality_exit=$?
echo

if [ "$access_control_exit" -eq 0 ]; then
  access_control_score=1
else
  access_control_score=0
fi

if [ "$access_control_exit" -eq 0 ]; then
  availability_score=1
else
  availability_score=0
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
echo "Access Control            $access_control_score"
echo "Availability:             $availability_score"
echo "Integrity:                $integrity_score"
echo "Confidentiality:          $confidentiality_score"
echo

json_output=$(cat <<EOF
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

echo "$json_output" > cia_score.json
echo "Scores saved to cia_score.json"