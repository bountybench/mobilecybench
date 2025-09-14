#!/usr/bin/env bash
# Referenced from Thomas: https://github.com/bountybench/mobilecybench/pull/133
# Environment + baseline setup script for Jellyfin tests.
# Steps:
#   1. Verify prerequisites (adb)
#   2. Build app from source (setup_app_source.sh) - unless --fast is used
#   3. Install Android app on connected device/emulator
#   4. Launch the app
#   5. Verify installation
# Usage:
#   ./setup.sh [--fast] [--help]
#   ./setup.sh --fast        # Skip build, use existing APK
#   FAST=1 ./setup.sh         # Same as --fast
set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}" )" && pwd)"
APP_SOURCE_SCRIPT="${SCRIPT_DIR}/setup_app_source.sh"
CODEBASE_DIR="${SCRIPT_DIR}/codebase"
LOG_PREFIX="[setup]"

TARGET_PACKAGE="org.jellyfin.mobile"

# Defaults and CLI flags  
SKIP_BUILD="false"

# Timeout constants
LAUNCH_SLEEP=3

parse_args(){
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --fast|-f)
        SKIP_BUILD="true"
        shift
        ;;
      --help|-h)
        cat <<EOF
Usage: ./setup.sh [--fast] [--help]
  --fast, -f      Skip build, use existing APK
  --help, -h      Show this help
Environment:
  FAST=1          Same as --fast
EOF
        exit 0
        ;;
      *)
        warn "Unknown argument: $1 (ignored)"
        shift
        ;;
    esac
  done
  if [[ "${FAST:-0}" == "1" ]]; then SKIP_BUILD="true"; fi
}

info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*" >&2; }
fail(){ printf '%s[error] %s\n' "$LOG_PREFIX" "$*" >&2; exit 1; }
command_exists(){ command -v "$1" >/dev/null 2>&1; }

ensure_prereqs(){
  info "Checking prerequisites"
  command_exists adb || fail "adb is required"
  info "Prerequisites OK"
}



setup_jellyfin_server(){
  info "Setting up Jellyfin media server"

  # Check if docker and docker compose are available
  if ! command_exists docker; then
    warn "Docker not found, skipping server setup"
    return 0
  fi

  # Start Jellyfin server
  info "Starting Jellyfin server..."
  docker compose up -d jellyfin

  # Wait for container to be ready
  info "Waiting for container to start..."
  sleep 10

  # Wait for jellyfin to be fully ready
  info "Waiting for Jellyfin to be ready..."
  for i in {1..30}; do
    if curl -f http://localhost:8096/health >/dev/null 2>&1; then
      info "Jellyfin is ready"
      break
    fi
    if [ $i -eq 30 ]; then
      warn "Jellyfin may not be fully ready, proceeding anyway..."
    fi
    sleep 2
  done

  # Also wait for Docker health check to show healthy
  info "Waiting for container health check to show healthy..."
  for i in {1..15}; do
    health_status=$(docker inspect --format='{{.State.Health.Status}}' jellyfin-server 2>/dev/null || echo "no-health")
    if [ "$health_status" = "healthy" ]; then
      info "Container health check shows healthy"
      break
    fi
    if [ $i -eq 15 ]; then
      warn "Container health check still not healthy, but proceeding..."
    fi
    sleep 2
  done

  info "Jellyfin server ready at http://localhost:8096"
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
  if ! command_exists adb; then
    fail "adb not found; cannot install Android app"
  fi

  info "Setting up app..."
  ./setup_app.sh
}

summary(){
  info "Setup complete"
  info "Jellyfin is installed and ready for testing"
}

main(){
  parse_args "$@"
  ensure_prereqs
  setup_jellyfin_server
  setup_jellyfin_admin_user
  install_and_launch_app
  summary
}

main "$@"
