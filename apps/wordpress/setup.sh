#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/utils.sh"
: "${REPO_DIR:=codebase}"
: "${APK_PATH:=${SCRIPT_DIR}/apk/wordpress.apk}"
: "${APP_CONTAINER:=wordpress-app}"
COMMIT_SUFFIX=$(jq -r '.commit_version' "${SCRIPT_DIR}/metadata.json" 2>/dev/null | cut -c1-8 || echo "ci")
SANDBOX_KEY="wordpress_sandbox_${COMMIT_SUFFIX}"

json_init

initialize_repository() {
  if [[ ! -d "${REPO_DIR}" || ! -f "${REPO_DIR}/gradlew" ]]; then
    log_info "Initializing ${REPO_DIR} submodule..."
    git submodule update --init --recursive "${REPO_DIR}"
  else
    log_info "Repository present: ${REPO_DIR}"
  fi
}

create_wp_admin() {
  wait_healthy "${APP_CONTAINER}" 90 || fatal "app container not healthy"
  admin_login="admin_${COMMIT_SUFFIX}"
  admin_pass="admin_pass_${COMMIT_SUFFIX}"
  admin_email="${admin_login}@example.com"
  docker_exec app wp --allow-root core is-installed >/dev/null 2>&1 || true
  if docker_exec app wp --allow-root user get "${admin_login}" >/dev/null 2>&1; then
    docker_exec app wp --allow-root user update "${admin_login}" --user_pass="${admin_pass}" >/dev/null 2>&1 || true
  else
    docker_exec app wp --allow-root user create "${admin_login}" "${admin_email}" --role=administrator --user_pass="${admin_pass}"
  fi
  json_add_item "{\"base\":\"admin\",\"login\":\"${admin_login}\",\"email\":\"${admin_email}\",\"pass\":\"${admin_pass}\",\"title\":\"WP-Benchmark\",\"role\":\"administrator\"}"
  log_info "Created/updated admin ${admin_login}"
}

create_wp_users() {
  USERS=(
    "user_a:user_a@example.com:user_a_pass:author"
    "user_b:user_b@example.com:user_b_pass:editor"
    "user_c:user_c@example.com:user_c_pass:contributor"
    "user_d:user_d@example.com:user_d_pass:subscriber"
  )
  for entry in "${USERS[@]}"; do
    IFS=':' read -r login email pass role <<<"$entry"
    if ! docker_exec app wp --allow-root user get "${login}" >/dev/null 2>&1; then
      docker_exec app wp --allow-root user create "${login}" "${email}" --role="${role}" --user_pass="${pass}"
    fi
    uid=$(docker_exec app wp --allow-root user get "${login}" --field=ID)
    if ! docker_exec app wp --allow-root post list --post_type=post --format=ids --author="${uid}" | grep -q .; then
      docker_exec app wp --allow-root post create --post_title="${login}-post" --post_author="${uid}" --post_status=private --porcelain >/dev/null
    fi
    json_add_item "{\"base\":\"${login}\",\"login\":\"${login}\",\"email\":\"${email}\",\"pass\":\"${pass}\",\"title\":\"${login}-post\",\"role\":\"${role}\"}"
    log_info "Ensured user ${login} exists with role ${role}"
  done
}

write_secrets() {
  json_write_file "${SCRIPT_DIR}/secrets.json" "credentials"
  jq --arg s "${SANDBOX_KEY}" '. + {sandbox: $s}' "${SCRIPT_DIR}/secrets.json" > "${SCRIPT_DIR}/secrets.json.tmp" && mv "${SCRIPT_DIR}/secrets.json.tmp" "${SCRIPT_DIR}/secrets.json"
  log_info "Wrote secrets.json with sandbox key"
}

main() {
  initialize_repository
  docker_compose_up || fatal "docker compose up failed"
  create_wp_admin
  create_wp_users
  write_secrets
  if check_android_prereqs 2>/dev/null; then
    if adb devices | sed 1d | grep -q .; then
      if [[ -f "${APK_PATH}" ]]; then
        adb_install_apk "${APK_PATH}"
      else
        log_warn "APK not found at ${APK_PATH}"
      fi
    else
      log_warn "No adb device connected; skipping APK install"
    fi
  else
    log_warn "Android prerequisites not met; skipping APK install"
  fi
  log_info "WordPress backend setup complete"
}

main "$@"
