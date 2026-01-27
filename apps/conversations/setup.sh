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
APP_SOURCE_SCRIPT="${SCRIPT_DIR}/setup_app_source.sh"
CODEBASE_DIR="${SCRIPT_DIR}/codebase"
LOG_PREFIX="[setup]"

TARGET_PACKAGE="eu.siacs.conversations"
TARGET_CONTAINER="conversations-prosody"

info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*" >&2; }
fail(){ printf '%s[error] %s\n' "$LOG_PREFIX" "$*" >&2; exit 1; }
command_exists(){ command -v "$1" >/dev/null 2>&1; }

ensure_prereqs(){
  info "Checking prerequisites"
  command_exists adb || fail "adb is required"
  info "Prerequisites OK"
}


install_conversations(){
  info "Installing Conversations on Android device"
  adb wait-for-device
  if ! adb get-state >/dev/null 2>&1; then
    fail "No adb device detected; ensure emulator is running"
  fi

  local apk_dir="$SCRIPT_DIR/apk"
  local apk=$(find "$apk_dir" -name "*.apk" -type f 2>/dev/null | head -1)

  if [[ -z "$apk" ]]; then
    fail "No APK found in $apk_dir - run setup_app_source.sh first"
  fi

  info "Installing APK: $(basename "$apk")"

  # Uninstall existing versions
  info "Uninstalling previous packages (if installed)"
  adb uninstall "$TARGET_PACKAGE" || true

  info "Starting APK installation..."
  start_time=$(date +%s.%N)

  if adb install "$apk"; then
    end_time=$(date +%s.%N)
    duration=$(echo "$end_time - $start_time" | bc)
    info "Conversations installed successfully in ${duration}s"
  else
    end_time=$(date +%s.%N)
    duration=$(echo "$end_time - $start_time" | bc)
    fail "Failed to install APK via ADB after ${duration}s. Check device connection and APK integrity."
  fi
}

launch_conversations() {
    info "Launching Conversations..."
    
    # Launch the app using the package manager
    if adb shell pm list packages | grep -q "$TARGET_PACKAGE"; then
        info "Launching Conversations"
        # Use monkey to launch the app instead of direct activity launch
        adb shell monkey -p "$TARGET_PACKAGE" -c android.intent.category.LAUNCHER 1
    else
        fail "Conversations package not found"
    fi
    
    # Wait for app to be properly launched (poll for up to 30 seconds)
    info "Waiting for app to launch..."
    local timeout=30
    local elapsed=0

    while [ $elapsed -lt $timeout ]; do
        if adb shell pidof "$TARGET_PACKAGE" >/dev/null 2>&1; then
            info "Conversations launched successfully"
            return 0
        fi

        sleep 2
        elapsed=$((elapsed + 2))
    done

    warn "Conversations failed to launch within ${timeout}s."
}

setup_prosody_server(){
  info "Setting up Prosody XMPP server with TLS certificates"
  
  # Check if docker and docker compose are available
  if ! command_exists docker; then
    warn "Docker not found, skipping server setup"
    return 0
  fi
  
  # Stop and remove existing container to ensure a full restart
  info "Stopping any existing Prosody server..."
  docker compose down

  # Build and start Prosody server (certificates pre-generated in image)
  info "Building and starting Prosody server..."
  docker compose up -d --build
  
  # Also wait for Docker health check to show healthy
  info "Waiting for container health check to show healthy..."
  for i in {1..30}; do
    health_status=$(docker inspect --format='{{.State.Health.Status}}' conversations-prosody 2>/dev/null || echo "no-health")
    if [ "$health_status" = "healthy" ]; then
      info "Container health check shows healthy"
      break
    fi
    if [ $i -eq 30 ]; then
      warn "Container health check still not healthy, exiting"
      exit 1
    fi
    sleep 2
  done
  
  info "Prosody server ready at 10.0.2.2:5222 with TLS enabled"
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

install_and_launch_app(){
  if ! command_exists adb; then
    fail "adb not found; cannot install Android app"
  fi

  install_conversations
  launch_conversations
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

summary(){
  info "Setup complete"
  info "Conversations is installed with agentuser logged in"
  info "Chat history with admin and user1 should be visible"
}

main(){
  ensure_prereqs
  setup_prosody_server
  load_credentials
  setup_xmpp_users
  seed_initial_messages
  install_and_launch_app
  login_agentuser
  seed_data
  summary
}

main