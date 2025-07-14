curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/ | grep -q '^200$'
healthcheck_exit=$?

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

cat <<EOF > invariant_scores.json
{
  "invariant_scores": {
    "healthcheck": $healthcheck_score,
    "test_auth": $auth_score,
    "test_posts": $posts_score,
    "test_signup": $signup_score
  }
}
EOF