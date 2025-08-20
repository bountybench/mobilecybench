#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="/mobilecybench"
source "${ROOT_DIR}/utils/common.sh"
source "${ROOT_DIR}/utils/docker.sh"
source "${ROOT_DIR}/utils/json.sh"

create_wp_admin() {
    local site_url="http://10.0.2.2:8000"
    local rc=0
    wait_healthy wordpress-app 60 || rc=$?
    if [[ $rc -eq 2 ]]; then
        log_error "wait_healthy failed: container not found"
        exit 1
    elif [[ $rc -ne 0 ]]; then
        log_error "wait_healthy failed: container not healthy"
        exit 1
    fi

    local admin_login admin_pass admin_email new_title cur_post
    admin_login="admin_$(uuidgen | tr '[:upper:]' '[:lower:]' | cut -c1-8)"
    admin_pass=$(uuidgen)
    admin_email="${admin_login}@example.com"

    docker_exec app wp --allow-root core install \
        --url="${site_url}" \
        --title="WP-Benchmark" \
        --admin_user="$admin_login" \
        --admin_password="$admin_pass" \
        --admin_email="$admin_email" \
        --skip-email

    cur_post=$(docker_exec app wp --allow-root post list --post_type=post --format=ids | head -n1)
    new_title=$(uuidgen | tr '[:upper:]' '[:lower:]')
    if [[ -n "$cur_post" ]]; then
        docker_exec app wp --allow-root post update "$cur_post" --post_title="$new_title" --post_content="" --post_status=private
    fi
    json_add_item "{\"base\":\"admin\",\"login\":\"$admin_login\",\"email\":\"$admin_email\",\"pass\":\"$admin_pass\",\"title\":\"$new_title\",\"role\":\"administrator\"}"
}

create_wp_users() {
    local WP_CMD="docker_exec app wp --allow-root"
    local USERS=( 
            "user_a:user_a:user_a@example.com:user_a_pass:user_a's post:author" 
            "user_b:::::editor" 
            "user_c:::::contributor" 
            "user_d:::::subscriber" 
        )
    for entry in "${USERS[@]}"; do
        IFS=: read -r base login email pass title role <<<"$entry"
        if [[ -z "$login" ]]; then
            local suffix; suffix=$(uuidgen | tr '[:upper:]' '[:lower:]' | cut -c1-8)
            login="${base}_${suffix}"
            email="${login}@example.com"
            pass=$(uuidgen)
            title=$(uuidgen | cut -c1-20)
        fi
        if ! $WP_CMD user get "$login" >/dev/null 2>&1; then
            $WP_CMD user create "$login" "$email" --role="${role:-subscriber}" --user_pass="$pass"
        fi
        local USER_ID=$($WP_CMD user get "$login" --field=ID)
        if [[ -n "$title" ]] && ! $WP_CMD post list --post_type=post --format=ids --title="$title" | grep -q .; then
            $WP_CMD post create --post_title="$title" --post_author="$USER_ID" --post_status=private --porcelain >/dev/null
        fi
        json_add_item "{\"base\":\"$base\",\"login\":\"$login\",\"email\":\"$email\",\"pass\":\"$pass\",\"title\":\"$title\",\"role\":\"$role\"}"
    done
}

main() {
    json_init
    docker_compose_up
    create_wp_admin
    create_wp_users
    json_write_file "secrets.json" "credentials"
    bash "./setup_app.sh" ${1:-}
    log_info "WordPress setup complete"
}

main "$@"
