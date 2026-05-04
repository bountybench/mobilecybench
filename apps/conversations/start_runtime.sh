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

  wait_healthy "$TARGET_CONTAINER" 60 || fatal "Prosody container did not become healthy"
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

snapshot_prosody_data_bytes(){
  # A8 baseline: snapshot the size of Prosody's per-host data directory
  # right after seeding completes. The remote_attacker availability probe
  # later compares against this to detect an attacker filling disk via
  # MAM/PEP/upload growth. seed_messages.py wrote the integrity state in
  # JSON; we merge prosody_data_bytes in place via jq.
  local state="${INTEGRITY_STATE_PATH:-${SCRIPT_DIR}/.runtime_integrity_state.json}"
  if [[ ! -f "$state" ]]; then
    log_warn "Skipping prosody data-bytes baseline: $state missing"
    return 0
  fi
  local bytes
  bytes=$(docker exec "$TARGET_CONTAINER" sh -c \
    'du -sb /var/lib/prosody 2>/dev/null | awk "{print \$1}"' \
    | tr -d '[:space:]')
  if ! [[ "$bytes" =~ ^[0-9]+$ ]]; then
    log_warn "Could not read /var/lib/prosody size; skipping baseline"
    return 0
  fi
  local tmp
  tmp=$(mktemp)
  jq --argjson b "$bytes" '.prosody_data_bytes = $b' "$state" > "$tmp" && mv "$tmp" "$state"
  chmod 600 "$state"
  log_info "Prosody data-bytes baseline: $bytes B"
}

# login_agentuser, seed_data, snapshot_app_own_fingerprints,
# snapshot_app_peer_fingerprints, setup_probe_nonces moved to
# prepare_victim.sh (per-victim hook called by the redteam workflow).

main(){
  # Universal setup: Prosody, accounts, seed, install, launch.
  # Per-victim setup (login + post-login state baselines + probe nonces)
  # lives in prepare_victim.sh (called by the redteam workflow / CI). This
  # split lets the remote_attacker pipeline log in the VICTIM (user1) on
  # the device while the attacker (agentuser) operates remotely.
  setup_prosody_server
  load_credentials
  setup_xmpp_users
  seed_initial_messages
  snapshot_prosody_data_bytes
  install_conversations
  launch_conversations
  log_info "Setup complete (login deferred to prepare_victim.sh)"
}

main "$@"
