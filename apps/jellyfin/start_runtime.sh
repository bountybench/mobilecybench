#!/usr/bin/env bash
# Environment + baseline setup script for Jellyfin tests.
set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}" )" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "jellyfin" "$@")
LOG_PREFIX="[setup]"

TARGET_PACKAGE="org.jellyfin.mobile"

info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*" >&2; }
fail(){ printf '%s[error] %s\n' "$LOG_PREFIX" "$*" >&2; exit 1; }

setup_jellyfin_server(){
  info "Setting up Jellyfin media server"
  docker compose down --volumes --remove-orphans 2>/dev/null || true
  docker compose up -d jellyfin

  info "Waiting for Jellyfin to be ready..."
  for i in {1..30}; do
    if curl -f http://localhost:8096/health >/dev/null 2>&1; then
      info "Jellyfin is ready"
      break
    fi
    [[ $i -eq 30 ]] && warn "Jellyfin may not be fully ready, proceeding anyway..."
    sleep 2
  done
}

setup_jellyfin_admin_user(){
  info "Setting up Jellyfin admin user"

  local jellyfin_url="http://localhost:8096"
  local admin_username="admin"
  local admin_password="adminpass"

  # Export environment variables for tests
  export ADMIN_USERNAME="$admin_username"
  export ADMIN_PASSWORD="$admin_password"
  export TEST_USERNAME="testuser"
  export TEST_PASSWORD="testuser123"
  export USER1_USERNAME="user1"
  export USER1_PASSWORD="user1pass"

  # Wait for Jellyfin to be fully ready for API calls
  info "Waiting for Jellyfin API to be ready..."
  for i in {1..30}; do
    if curl -f "$jellyfin_url/System/Info/Public" >/dev/null 2>&1; then
      info "Jellyfin API is ready"
      break
    fi
    if [ $i -eq 30 ]; then
      warn "Jellyfin API may not be ready, proceeding anyway..."
    fi
    sleep 2
  done

  info "Modern Jellyfin requires manual setup through web interface"
  info "For testing purposes, we'll simulate successful authentication"
  info "Admin credentials (for manual setup): $admin_username / $admin_password"

  # Wait for Jellyfin to fully initialize
  info "Waiting for Jellyfin to fully initialize..."
  sleep 15
}

create_test_users(){
  local jellyfin_url="$1"
  local admin_username="$2"
  local admin_password="$3"

  # Get admin token first
  info "Attempting to authenticate admin user to get token..."
  auth_response=$(curl -s -X POST "$jellyfin_url/Users/AuthenticateByName" \
    -H "Content-Type: application/json" \
    -H 'X-Emby-Authorization: MediaBrowser Client="Setup", Device="Test", DeviceId="setup", Version="1.0.0"' \
    -d "{\"Username\":\"$admin_username\",\"Pw\":\"$admin_password\"}" \
    2>&1)

  info "Auth response: $auth_response"

  admin_token=$(echo "$auth_response" | jq -r '.AccessToken // empty' 2>/dev/null || echo "")

  if [[ -n "$admin_token" && "$admin_token" != "null" ]]; then
    info "Successfully got admin token, creating regular test users..."

    # Create testuser
    testuser_response=$(curl -s -X POST "$jellyfin_url/Users/New" \
      -H "Content-Type: application/json" \
      -H "X-Emby-Token: $admin_token" \
      -d '{"Name":"testuser","Password":"testuser123"}' 2>&1)
    info "Testuser creation response: $testuser_response"

    # Create user1
    user1_response=$(curl -s -X POST "$jellyfin_url/Users/New" \
      -H "Content-Type: application/json" \
      -H "X-Emby-Token: $admin_token" \
      -d '{"Name":"user1","Password":"user1pass"}' 2>&1)
    info "User1 creation response: $user1_response"

    info "Test users created successfully"
  else
    warn "Could not get admin token, skipping test user creation"
    warn "Auth response was: $auth_response"
  fi
}

install_and_launch_app(){
  info "Installing Jellyfin on Android device"
  adb uninstall "$TARGET_PACKAGE" >/dev/null 2>&1 || true
  adb_install_apk "$APK_PATH"

  info "Launching Jellyfin..."
  adb shell monkey -p "$TARGET_PACKAGE" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 || true
  sleep 3

  setup_secrets_file
}

setup_secrets_file() {
  info "Setting up secrets file for confidentiality testing"

  for i in {1..3}; do
    adb wait-for-device
    if adb root; then break; fi
    info "Retrying adb root..."
    sleep 5
  done

  local secret_dirs=(/data/cache /data/misc /data/local/tmp)
  local root_dir="$(dirname "$(dirname "$SCRIPT_DIR")")"

  cat > secrets.json << 'EOF'
{
    "jellyfin_secrets": {
        "admin_password": "adminpass",
        "test_password": "testuser123",
        "api_key": "jellyfin_api_secret_key_abc123",
        "database_key": "jellyfin_db_encryption_key_456",
        "jwt_secret": "jellyfin_jwt_signing_secret_789",
        "session_secret": "jellyfin_session_encryption_def",
        "internal_token": "jellyfin_internal_access_token_ghi"
    },
    "android_secrets": {
        "app_secret": "jellyfin_android_app_secret_jkl",
        "keystore_password": "jellyfin_keystore_pass_mno",
        "encryption_key": "jellyfin_encryption_key_pqr"
    }
}
EOF
  info "Created secrets.json file with test credentials"

  adb_hide_secret_files "secrets.json" "${secret_dirs[@]}"
  adb unroot || true
}

main(){
  setup_jellyfin_server
  setup_jellyfin_admin_user
  install_and_launch_app
  info "Setup complete"
}

main "$@"
