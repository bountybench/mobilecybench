#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "conversations" "$@")
cd "$SCRIPT_DIR"

TARGET_PACKAGE="eu.siacs.conversations"
TARGET_CONTAINER="conversations-prosody"

install_conversations(){
  log_info "Installing Conversations on Android device"
  adb uninstall "$TARGET_PACKAGE" 2>/dev/null || true
  adb_install_apk "$APK_PATH"
}

launch_conversations() {
    log_info "Launching Conversations..."
    adb shell monkey -p "$TARGET_PACKAGE" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 || true
    sleep 3
    if adb shell pidof "$TARGET_PACKAGE" >/dev/null 2>&1; then
        log_info "Conversations launched successfully"
    else
        log_warn "Conversations may not have launched properly"
    fi
}

setup_prosody_server(){
  log_info "Setting up Prosody XMPP server"
  docker compose down 2>/dev/null || true
  docker compose up -d --build

  log_info "Waiting for container health check..."
  for i in {1..30}; do
    health_status=$(docker inspect --format='{{.State.Health.Status}}' "$TARGET_CONTAINER" 2>/dev/null || echo "no-health")
    [[ "$health_status" = "healthy" ]] && { log_info "Prosody container healthy"; break; }
    [[ $i -eq 30 ]] && { log_warn "Container health check not healthy, exiting"; exit 1; }
    sleep 2
  done
}

load_credentials(){
  log_info "Loading static XMPP credentials from secrets.json"
  local secrets_file="${SCRIPT_DIR}/secrets.json"

  if [[ ! -f "$secrets_file" ]]; then
    fatal "secrets.json not found at $secrets_file"
  fi

  ADMIN_PASSWORD=$(jq -r '.admin_password' "$secrets_file")
  TESTUSER_PASSWORD=$(jq -r '.testuser_password' "$secrets_file")
  USER1_PASSWORD=$(jq -r '.user1_password' "$secrets_file")
  USER2_PASSWORD=$(jq -r '.user2_password' "$secrets_file")

  log_info "Static credentials loaded successfully"
}

setup_xmpp_users(){
  log_info "Setting up XMPP test users with generated credentials"

  local container_name="$TARGET_CONTAINER"
  local domain="10.0.2.2"

  log_info "Creating admin user: admin@$domain with password: $ADMIN_PASSWORD"
  if docker exec "$container_name" prosodyctl register admin "$domain" "$ADMIN_PASSWORD"; then
    log_info "Admin user created successfully"
  fi

  log_info "Creating test user: testuser@$domain with password: $TESTUSER_PASSWORD"
  if docker exec "$container_name" prosodyctl register testuser "$domain" "$TESTUSER_PASSWORD"; then
    log_info "Test user created successfully"
  fi

  log_info "Creating regular user: user1@$domain with password: $USER1_PASSWORD"
  if docker exec "$container_name" prosodyctl register user1 "$domain" "$USER1_PASSWORD"; then
    log_info "Regular user1 created successfully"
  fi

  log_info "Creating regular user: user2@$domain with password: $USER2_PASSWORD"
  if docker exec "$container_name" prosodyctl register user2 "$domain" "$USER2_PASSWORD"; then
    log_info "Regular user2 created successfully"
  fi

  log_info "Creating agent user: agentuser@$domain with password: agentpass"
  if docker exec "$container_name" prosodyctl register agentuser "$domain" "agentpass"; then
    log_info "Agent user created successfully"
  fi
}

seed_initial_messages(){
  log_info "Seeding initial chat messages between users"

  log_info "Running message seeding script..."
  if python3 "${SCRIPT_DIR}/seed_messages.py"; then
    log_info "Initial messages seeded successfully"
  else
    fatal "Message seeding failed"
  fi
}

login_agentuser(){
  log_info "Logging in as agentuser..."

  local app_package="$TARGET_PACKAGE"
  adb shell pm grant "$app_package" android.permission.READ_CONTACTS 2>/dev/null || true
  adb shell pm grant "$app_package" android.permission.POST_NOTIFICATIONS 2>/dev/null || true

  if python3 "${SCRIPT_DIR}/ui_automation/login.py" \
      --username "agentuser@10.0.2.2" \
      --password "agentpass"; then
    log_info "agentuser logged in successfully"
  else
    fatal "Failed to login agentuser"
  fi
}

seed_data(){
  log_info "Seeding conversation data..."

  if python3 "${SCRIPT_DIR}/seed_messages.py" --trigger-only; then
    log_info "Conversation data seeded successfully"
  else
    log_warn "Failed to seed conversation data (non-fatal)"
  fi

  sleep 2
}

main(){
  setup_prosody_server
  load_credentials
  setup_xmpp_users
  seed_initial_messages
  install_conversations
  launch_conversations
  login_agentuser
  seed_data
  log_info "Setup complete"
}

main "$@"
