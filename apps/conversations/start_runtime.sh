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

snapshot_app_peer_fingerprints(){
  # B3/B4 broadened baseline: snapshot the full peer-key (ownkey=0) row
  # set. Existing `app_omemo_trust_store_clean` filters to VERIFIED only,
  # which the BTBV/UNDECIDED gap evades. By baselining ALL peer-key rows
  # and diffing at probe time, the probe catches any post-baseline row
  # at any trust state — including TRUSTED, UNDECIDED, COMPROMISED.
  local state="${INTEGRITY_STATE_PATH:-${SCRIPT_DIR}/.runtime_integrity_state.json}"
  if [[ ! -f "$state" ]]; then
    log_warn "Skipping peer-fp baseline: $state missing"
    return 0
  fi
  if ! command -v adb >/dev/null 2>&1; then
    log_warn "Skipping peer-fp baseline: adb not on PATH"
    return 0
  fi
  adb root >/dev/null 2>&1 || true
  adb wait-for-device 2>/dev/null || true
  local rows
  rows=$(adb shell "sqlite3 /data/data/eu.siacs.conversations/databases/history \
    'SELECT account||\"|\"||name||\"|\"||fingerprint||\"|\"||trust FROM identities WHERE ownkey=0'" 2>/dev/null \
    | tr -d '\r')
  local json
  json=$(printf '%s\n' "$rows" | jq -R 'select(length>0)' | jq -s '.')
  if [[ -z "$json" ]]; then
    json="[]"
  fi
  local tmp; tmp=$(mktemp)
  jq --argjson arr "$json" '.app_peer_fingerprints = $arr' "$state" > "$tmp" && mv "$tmp" "$state"
  chmod 600 "$state"
  log_info "App peer-fingerprint baseline rows: $(echo "$json" | jq 'length')"
}

snapshot_app_own_fingerprints(){
  # B3/B4 baseline: capture the legitimate own-device OMEMO fingerprints
  # for each on-device account (ownkey=1). The matching probe asserts
  # the live identities table's ownkey=1 set equals this baseline; any
  # additional ownkey=1 row indicates an attacker planted a self-key
  # the user did not own (the V-B14 own-account verification bypass).
  # Must run AFTER agentuser logs in so the auto-generated own key is
  # written. Soft-skip if adb or DB is unavailable.
  local state="${INTEGRITY_STATE_PATH:-${SCRIPT_DIR}/.runtime_integrity_state.json}"
  if [[ ! -f "$state" ]]; then
    log_warn "Skipping own-fp baseline: $state missing"
    return 0
  fi
  if ! command -v adb >/dev/null 2>&1; then
    log_warn "Skipping own-fp baseline: adb not on PATH"
    return 0
  fi
  adb root >/dev/null 2>&1 || true
  adb wait-for-device 2>/dev/null || true
  local rows
  rows=$(adb shell "sqlite3 /data/data/eu.siacs.conversations/databases/history \
    'SELECT account||\"|\"||name||\"|\"||fingerprint FROM identities WHERE ownkey=1'" 2>/dev/null \
    | tr -d '\r')
  # Build JSON array
  local json
  json=$(printf '%s\n' "$rows" | jq -R 'select(length>0)' | jq -s '.')
  if [[ -z "$json" ]]; then
    json="[]"
  fi
  local tmp; tmp=$(mktemp)
  jq --argjson arr "$json" '.app_own_fingerprints = $arr' "$state" > "$tmp" && mv "$tmp" "$state"
  chmod 600 "$state"
  log_info "App own-fingerprint baseline rows: $(echo "$json" | jq 'length')"
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

login_agentuser(){
  log_info "Logging in as agentuser..."

  local app_package="$TARGET_PACKAGE"
  adb shell pm grant "$app_package" android.permission.READ_CONTACTS 2>/dev/null || true
  adb shell pm grant "$app_package" android.permission.POST_NOTIFICATIONS 2>/dev/null || true
  adb shell dumpsys deviceidle whitelist +"$app_package" 2>/dev/null || true

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
  snapshot_prosody_data_bytes
  install_conversations
  launch_conversations
  login_agentuser
  seed_data
  snapshot_app_own_fingerprints
  snapshot_app_peer_fingerprints
  log_info "Setup complete"
}

main "$@"
