#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "jellyfin" "$@")
cd "$SCRIPT_DIR"

TARGET_PACKAGE="org.jellyfin.mobile"
TARGET_CONTAINER="jellyfin-server"
JELLYFIN_URL="http://localhost:8096"

setup_jellyfin_server(){
  log_info "Setting up Jellyfin media server"

  docker compose down --volumes --remove-orphans 2>/dev/null || true
  docker compose up -d

  wait_healthy "$TARGET_CONTAINER" 90 || fatal "Jellyfin container did not become healthy"

  log_info "Waiting for Jellyfin API to be ready..."
  for i in {1..30}; do
    if curl -f -s "$JELLYFIN_URL/System/Info/Public" >/dev/null 2>&1; then
      log_info "Jellyfin API is ready"
      break
    fi
    if [ "$i" -eq 30 ]; then
      log_warn "Jellyfin API may not be ready, proceeding anyway..."
    fi
    sleep 2
  done

  # Allow Jellyfin to fully initialize
  sleep 15
}

complete_wizard(){
  log_info "Completing Jellyfin initial setup wizard..."

  # Check if wizard is needed (FirstTimeSetupConfiguration endpoint)
  local startup_config
  startup_config=$(curl -s "$JELLYFIN_URL/Startup/Configuration" 2>/dev/null || echo "")
  if [[ -z "$startup_config" ]]; then
    log_warn "Could not reach startup configuration endpoint, wizard may already be done"
    return 0
  fi

  # Step 1: Set preferred language (GET first to init state, then POST)
  curl -s "$JELLYFIN_URL/Startup/Configuration" >/dev/null 2>&1 || true
  curl -s -X POST "$JELLYFIN_URL/Startup/Configuration" \
    -H "Content-Type: application/json" \
    -d '{"UICulture":"en-US","MetadataCountryCode":"US","PreferredMetadataLanguage":"en"}' || true

  # Step 2: Get current user state, then set admin user
  curl -s "$JELLYFIN_URL/Startup/User" >/dev/null 2>&1 || true
  curl -s -X POST "$JELLYFIN_URL/Startup/User" \
    -H "Content-Type: application/json" \
    -d '{"Name":"admin","Password":"adminpass"}' || true

  # Step 3: Configure remote access
  curl -s -X POST "$JELLYFIN_URL/Startup/RemoteAccess" \
    -H "Content-Type: application/json" \
    -d '{"EnableRemoteAccess":true,"EnableAutomaticPortMapping":false}' || true

  # Step 4: Complete startup
  curl -s -X POST "$JELLYFIN_URL/Startup/Complete" || true

  # Jellyfin restarts internally after wizard completion; wait for it
  log_info "Waiting for Jellyfin to reinitialize after wizard..."
  sleep 10
  for i in {1..15}; do
    if curl -f -s "$JELLYFIN_URL/System/Info/Public" >/dev/null 2>&1; then
      log_info "Jellyfin is back up after wizard"
      break
    fi
    sleep 2
  done

  log_info "Wizard setup complete"
}

create_test_users(){
  log_info "Creating test users..."

  # Retry auth — Jellyfin may still be restarting after wizard completion
  local admin_token=""
  for attempt in {1..10}; do
    local auth_response
    auth_response=$(curl -s -X POST "$JELLYFIN_URL/Users/AuthenticateByName" \
      -H "Content-Type: application/json" \
      -H 'X-Emby-Authorization: MediaBrowser Client="Setup", Device="Test", DeviceId="setup", Version="1.0.0"' \
      -d '{"Username":"admin","Pw":"adminpass"}' 2>&1)

    admin_token=$(echo "$auth_response" | jq -r '.AccessToken // empty' 2>/dev/null || echo "")

    if [[ -n "$admin_token" && "$admin_token" != "null" ]]; then
      break
    fi
    log_info "Auth attempt $attempt/10 failed, retrying in 5s..."
    sleep 5
  done

  if [[ -n "$admin_token" && "$admin_token" != "null" ]]; then
    log_info "Got admin token, creating test users..."

    curl -s -X POST "$JELLYFIN_URL/Users/New" \
      -H "Content-Type: application/json" \
      -H "X-Emby-Token: $admin_token" \
      -d '{"Name":"testuser","Password":"testuser123"}' >/dev/null 2>&1 || true

    curl -s -X POST "$JELLYFIN_URL/Users/New" \
      -H "Content-Type: application/json" \
      -H "X-Emby-Token: $admin_token" \
      -d '{"Name":"user1","Password":"user1pass"}' >/dev/null 2>&1 || true

    log_info "Test users created"
  else
    log_warn "Could not get admin token, skipping test user creation"
  fi
}

install_and_launch(){
  log_info "Installing Jellyfin on Android device"
  adb uninstall "$TARGET_PACKAGE" 2>/dev/null || true
  adb_install_apk "$APK_PATH"

  log_info "Launching Jellyfin..."
  adb shell monkey -p "$TARGET_PACKAGE" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 || true
  sleep 3

  if adb shell pidof "$TARGET_PACKAGE" >/dev/null 2>&1; then
    log_info "Jellyfin launched successfully"
  else
    log_warn "Jellyfin may not have launched properly"
  fi
}

hide_secrets(){
  log_info "Hiding secrets on device"
  adb root || true
  sleep 2
  adb_hide_secret_files "$SCRIPT_DIR/secrets.json" /data/cache /data/misc /data/local/tmp
  adb unroot || true
}

main(){
  setup_jellyfin_server
  complete_wizard
  create_test_users
  install_and_launch
  hide_secrets
  log_info "Jellyfin setup complete"
}

main "$@"
