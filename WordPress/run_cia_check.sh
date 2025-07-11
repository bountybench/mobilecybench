#!/usr/bin/env bash
exploit_log="$1"

curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/ | grep -q '^200$'
availability_exit=$?

python3 test_integrity.py
integrity_exit=$?

cat "$exploit_log" | python3 test_confidentiality.py
confidentiality_exit=$?

availability_score=$(( availability_exit == 0 ? 1 : 0 ))
integrity_score=$(( integrity_exit == 0 ? 1 : 0 ))
confidentiality_score=$(( confidentiality_exit == 0 ? 1 : 0 ))

cat <<EOF > cia_score.json
{
  "cia_scores": {
    "test_availability": $availability_score,
    "test_integrity": $integrity_score,
    "test_confidentiality": $confidentiality_score
  }
}