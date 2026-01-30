#!/usr/bin/env bash
# Environment + baseline setup script for Conversations tests.
# Steps:
#   1. Verify prerequisites (adb)
#   2. Install Android app on connected device/emulator
#   3. Launch the app
#   4. Verify installation

set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}" )" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "conversations" "$@")
LOG_PREFIX="[setup]"

TARGET_PACKAGE="eu.siacs.conversations"
TARGET_CONTAINER="conversations-prosody"

info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*" >&2; }
fail(){ printf '%s[error] %s\n' "$LOG_PREFIX" "$*" >&2; exit 1; }

install_conversations(){
  info "Installing Conversations on Android device"
  adb uninstall "$TARGET_PACKAGE" 2>/dev/null || true
  adb_install_apk "$APK_PATH"
}

launch_conversations() {
    info "Launching Conversations..."
    adb shell monkey -p "$TARGET_PACKAGE" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 || true
    sleep 3
    if adb shell pidof "$TARGET_PACKAGE" >/dev/null 2>&1; then
        info "Conversations launched successfully"
    else
        warn "Conversations may not have launched properly"
    fi
}

setup_prosody_server(){
  info "Setting up Prosody XMPP server"
  docker compose down 2>/dev/null || true
  docker compose up -d --build

  info "Waiting for container health check..."
  for i in {1..30}; do
    health_status=$(docker inspect --format='{{.State.Health.Status}}' "$TARGET_CONTAINER" 2>/dev/null || echo "no-health")
    [[ "$health_status" = "healthy" ]] && { info "Prosody container healthy"; break; }
    [[ $i -eq 30 ]] && { warn "Container health check not healthy, exiting"; exit 1; }
    sleep 2
  done
}

load_credentials(){
  info "Loading static XMPP credentials from secrets.json"
  local secrets_file="${SCRIPT_DIR}/secrets.json"

  if [[ ! -f "$secrets_file" ]]; then
    fail "secrets.json not found at $secrets_file"
  fi

  # Load passwords from secrets.json
  ADMIN_PASSWORD=$(jq -r '.admin_password' "$secrets_file")
  TESTUSER_PASSWORD=$(jq -r '.testuser_password' "$secrets_file")
  USER1_PASSWORD=$(jq -r '.user1_password' "$secrets_file")
  USER2_PASSWORD=$(jq -r '.user2_password' "$secrets_file")


  info "Static credentials loaded successfully"
}

setup_xmpp_users(){
  info "Setting up XMPP test users with generated credentials"
  
  local container_name="$TARGET_CONTAINER"
  local domain="10.0.2.2"
  
  # Create admin user
  info "Creating admin user: admin@$domain with password: $ADMIN_PASSWORD"
  if docker exec "$container_name" prosodyctl register admin "$domain" "$ADMIN_PASSWORD"; then
    info "Admin user created successfully"
  fi
  
  # Create test users
  info "Creating test user: testuser@$domain with password: $TESTUSER_PASSWORD"
  if docker exec "$container_name" prosodyctl register testuser "$domain" "$TESTUSER_PASSWORD"; then
    info "Test user created successfully"
  fi
  
  info "Creating regular user: user1@$domain with password: $USER1_PASSWORD"
  if docker exec "$container_name" prosodyctl register user1 "$domain" "$USER1_PASSWORD"; then
    info "Regular user1 created successfully"
  fi
  
  info "Creating regular user: user2@$domain with password: $USER2_PASSWORD"  
  if docker exec "$container_name" prosodyctl register user2 "$domain" "$USER2_PASSWORD"; then
    info "Regular user2 created successfully"
  fi
  
  # Create agent user (hardcoded credentials from metadata.json)
  info "Creating agent user: agentuser@$domain with password: agentpass"
  if docker exec "$container_name" prosodyctl register agentuser "$domain" "agentpass"; then
    info "Agent user created successfully"
  fi
}

seed_initial_messages(){
  info "Seeding initial chat messages between users"

  # Run the seed script directly (hits localhost:5281 which is exposed by docker-compose)
  info "Running message seeding script..."
  if python3 "${SCRIPT_DIR}/seed_messages.py"; then
    info "Initial messages seeded successfully"
  else
    fail "Message seeding failed"
  fi
}

login_agentuser(){
  info "Logging in as agentuser..."

  # Pre-grant permissions to avoid permission dialogs
  local app_package="$TARGET_PACKAGE"
  adb shell pm grant "$app_package" android.permission.READ_CONTACTS 2>/dev/null || true
  adb shell pm grant "$app_package" android.permission.POST_NOTIFICATIONS 2>/dev/null || true

  # Run login automation
  if python3 "${SCRIPT_DIR}/ui_automation/login.py" \
      --username "agentuser@10.0.2.2" \
      --password "agentpass"; then
    info "agentuser logged in successfully"
  else
    fail "Failed to login agentuser"
  fi
}

seed_data(){
  info "Seeding conversation data..."

  # Send trigger messages from other users to agentuser
  if python3 "${SCRIPT_DIR}/seed_messages.py" --trigger-only; then
    info "Conversation data seeded successfully"
  else
    warn "Failed to seed conversation data (non-fatal)"
  fi

  # Give the app a moment to receive messages
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
  info "Setup complete"
}

main