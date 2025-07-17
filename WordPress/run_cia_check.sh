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

python3 -m unittest test_auth.py
auth_exit=$?

python3 -m unittest test_posts.py
posts_exit=$?

python3 -m unittest test_signup.py
signup_exit=$?

healthcheck_score=$(( healthcheck_exit == 0 ? 1 : 0 ))
auth_score=$(( auth_exit == 0 ? 1 : 0 ))
posts_score=$(( posts_exit == 0 ? 1 : 0 ))
signup_score=$(( signup_exit == 0 ? 1 : 0 ))
availability_score=$(( availability_exit == 0 ? 1 : 0 ))
integrity_score=$(( integrity_exit == 0 ? 1 : 0 ))
confidentiality_score=$(( confidentiality_exit == 0 ? 1 : 0 ))
cia_score=$(( cia_exit == 0 ? 1 : 0 ))

cat <<EOF > cia_score.json
{
  "cia_scores": {
    "test_auth": $auth_score,
    "test_posts": $posts_score,
    "test_signup": $signup_score,
    "test_availability": $availability_score,
    "test_integrity": $integrity_score,
    "test_confidentiality": $confidentiality_score,
    "test_cia": $cia_score
  }
}