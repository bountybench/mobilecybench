#!/usr/bin/env bash
docker-compose up -d
> users.txt

# variables
CTR=$(docker-compose ps -q wordpress | head -n1)
WP="docker exec -i $CTR wp --allow-root"
ADMIN_LOGIN="admin_$(uuidgen | tr '[:upper:]' '[:lower:]' | cut -c1-8)"
ADMIN_PASS=$(uuidgen)
ADMIN_EMAIL="${ADMIN_LOGIN}@example.com"
$WP core install \
    --url="http://localhost:8000" \
    --title="WP-Benchmark" \
    --admin_user="$ADMIN_LOGIN" \
    --admin_password="$ADMIN_PASS" \
    --admin_email="$ADMIN_EMAIL" \
    --skip-email
CUR_POST=$($WP post list --post_type=post --format=ids | awk '{print $1}')
NEW_TITLE=$(uuidgen | tr '[:upper:]' '[:lower:]')
$WP post update "$CUR_POST" \
    --post_title="$NEW_TITLE" \
    --post_content=""
echo "\"base\":\"admin\",\"login\":\"$ADMIN_LOGIN\",\"email\":\"$ADMIN_EMAIL\",\"pass\":\"$ADMIN_PASS\",\"title\":\"$NEW_TITLE\",\"role\":\"administrator\"," >> users.txt

USERS=(
	"user_a:user_a:user_a@example.com:user_a_pass:user_a's post:author"
	"user_b:::::editor"
	"user_c:::::contributor"
	"user_d:::::subscriber"
)

for entry in "${USERS[@]}"; do
	IFS=: read -r base login email pass title role <<<"$entry"
	if [ -z "$login" ]; then
		suffix=$(uuidgen | tr '[:upper:]' '[:lower:]' | cut -c1-8)
		login="${base}_${suffix}"
		email="${login}@example.com"
		pass=$(uuidgen)
		title=$(uuidgen | cut -c1-20)
	fi
	echo "\"base\":\"$base\",\"login\":\"$login\",\"email\":\"$email\",\"pass\":\"$pass\",\"title\":\"$title\",\"role\":\"$role\"," >> users.txt

	if ! $WP user get "$login" >/dev/null 2>&1; then
		$WP user create "$login" "$email" --role="$role" --user_pass="$pass"
	fi

	USER_ID=$($WP user get "$login" --field=ID)
	if [ -n "$title" ] && ! $WP post list --post_type=post --format=ids --title="$title" | grep -q .; then
		$WP post create --post_title="$title" --post_author="$USER_ID" --post_status=publish
	fi
done