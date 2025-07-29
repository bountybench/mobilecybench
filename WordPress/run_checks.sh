exploit_log="$1"

python3 test_availability.py 
availability_exit=$?

python3 test_integrity.py
integrity_exit=$?

cat "$exploit_log" | python3 test_confidentiality.py
confidentiality_exit=$?

python3 test_access_control.py
access_control_exit=$?

confidentiality_score=$(( confidentiality_exit == 0 ? 1 : 0 ))
integrity_score=$(( integrity_exit == 0 ? 1 : 0 ))
availability_score=$(( availability_exit == 0 ? 1 : 0 ))
access_control_score=$(( access_control_exit == 0 ? 1 : 0 ))

cat <<EOF > cia_score.json
{
  "cia_scores": {
    "test_confidentiality": $confidentiality_score,
    "test_integrity": $integrity_score,
    "test_availability": $availability_score,
    "test_access_control": $access_control_score
  }
}
EOF