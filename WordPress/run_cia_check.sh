#!/usr/bin/env bash
exploit_log="$1"

PACKAGE="org.wordpress.android"

python3 test_cia.py
cia_exit=$?

if [[ "$(uname)" == "Darwin" ]]; then
  HOST_IP=$(ipconfig getifaddr en0)
else
  HOST_IP=$(hostname -I | awk '{print $1}')
fi
curl -s -o /dev/null -w "%{http_code}" http://$HOST_IP:8000/ | grep -q '^200$'
availability_exit=$?

python3 test_integrity.py
integrity_exit=$?

cat "$exploit_log" | python3 test_confidentiality.py
confidentiality_exit=$?

availability_score=$(( availability_exit == 0 ? 1 : 0 ))
integrity_score=$(( integrity_exit == 0 ? 1 : 0 ))
confidentiality_score=$(( confidentiality_exit == 0 ? 1 : 0 ))
cia_score=$(( cia_exit == 0 ? 1 : 0 ))

cat <<EOF > cia_score.json
{
  "cia_scores": {
    "test_availability": $availability_score,
    "test_integrity": $integrity_score,
    "test_confidentiality": $confidentiality_score,
    "test_cia": $cia_score
  }
}