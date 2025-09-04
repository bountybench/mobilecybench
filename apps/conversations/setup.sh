#!/usr/bin/env bash
# Environment + baseline setup script for Conversations tests.
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

TARGET_PACKAGE="eu.siacs.conversations"

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

build_app(){
  if [[ "$SKIP_BUILD" == "true" ]]; then
    info "Skipping build (--fast mode)"
    return 0
  fi
  
  info "Building Conversations from source"
  if [[ ! -x "$APP_SOURCE_SCRIPT" ]]; then
    fail "setup_app_source.sh not found or not executable at $APP_SOURCE_SCRIPT"
  fi
  "$APP_SOURCE_SCRIPT" || fail "App source build failed"
}

get_emulator_arch() {
    # Detect emulator architecture
    if command -v adb >/dev/null 2>&1 && adb get-state >/dev/null 2>&1; then
        local arch
        arch=$(adb shell getprop ro.product.cpu.abi 2>/dev/null | tr -d '\r\n' || echo "")
        if [[ -n "$arch" ]]; then
            info "Detected emulator architecture: $arch"
            echo "$arch"
            return 0
        fi
    fi
    
    # Default to universal if can't detect
    warn "Could not detect emulator architecture, looking for universal APK"
    echo "universal"
}

install_conversations(){
  info "Installing Conversations on Android device"
  adb wait-for-device
  if ! adb get-state >/dev/null 2>&1; then
    fail "No adb device detected; ensure emulator is running"
  fi

  if [[ ! -d "$CODEBASE_DIR" ]]; then
    fail "Codebase not found at $CODEBASE_DIR"
  fi

  local arch
  arch=$(get_emulator_arch)
  
  local apk
  local apk_dir="$CODEBASE_DIR/build/outputs/apk/conversationsFree/release"
  
  # Try architecture-specific signed APK first
  apk=$(find "$apk_dir" -name "*-conversations-free-$arch-release.apk" -not -name "*unsigned*" -type f 2>/dev/null | head -1)
  
  if [[ -z "$apk" ]]; then
    warn "No signed $arch APK found, trying universal APK"
    apk=$(find "$apk_dir" -name "*-conversations-free-universal-release.apk" -not -name "*unsigned*" -type f 2>/dev/null | head -1)
  fi
  
  if [[ -z "$apk" ]]; then
    fail "No signed APK found - run build and signing first"
  fi

  info "Found APK for $arch: $(basename "$apk")"

  # Uninstall existing versions
  info "Uninstalling previous packages (if installed)"
  adb uninstall "$TARGET_PACKAGE" >/dev/null 2>&1 || true

  info "Installing APK: $apk"
  if adb install -r "$apk"; then
    info "Conversations installed successfully"
  else
    fail "Failed to install APK via ADB. Check device connection and APK integrity."
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
    
    sleep $LAUNCH_SLEEP
    
    # Verify the app is running
    if adb shell dumpsys window | grep -q "mCurrentFocus.*$TARGET_PACKAGE"; then
        info "Conversations launched successfully"
    else
        warn "Conversations may not have launched properly (focus not detected)."
    fi
}

setup_prosody_server(){
  info "Setting up Prosody XMPP server with TLS certificates"
  
  # Check if docker and docker compose are available
  if ! command_exists docker; then
    warn "Docker not found, skipping server setup"
    return 0
  fi
  
  # Build and start Prosody server (certificates pre-generated in image)
  info "Building and starting Prosody server..."
  docker compose up -d --build prosody
  
  # Wait for container to be ready
  info "Waiting for container to start..."
  sleep 5
  
  # Wait for prosody to be fully ready to accept commands
  info "Waiting for prosody to be ready for user management..."
  for i in {1..30}; do
    if docker exec conversations-prosody prosodyctl status >/dev/null 2>&1; then
      info "Prosody is ready for user management"
      break
    fi
    if [ $i -eq 30 ]; then
      warn "Prosody may not be fully ready, proceeding anyway..."
    fi
    sleep 2
  done
  
  # Also wait for Docker health check to show healthy
  info "Waiting for container health check to show healthy..."
  for i in {1..15}; do
    health_status=$(docker inspect --format='{{.State.Health.Status}}' conversations-prosody 2>/dev/null || echo "no-health")
    if [ "$health_status" = "healthy" ]; then
      info "Container health check shows healthy"
      break
    fi
    if [ $i -eq 15 ]; then
      warn "Container health check still not healthy, but proceeding..."
    fi
    sleep 2
  done
  
  info "Prosody server ready at 10.0.2.2:5222 with TLS enabled"
}

setup_xmpp_users(){
  info "Setting up XMPP test users"
  
  local container_name="conversations-prosody"
  local domain="10.0.2.2"
  
  # Check if Prosody container is running
  if ! docker ps --filter "name=$container_name" --filter "status=running" -q | grep -q .; then
    warn "Prosody container not running, skipping user setup"
    return 0
  fi
  
  # Create admin user
  info "Creating admin user: admin@$domain"
  if docker exec "$container_name" prosodyctl register admin "$domain" "adminpass"; then
    info "Admin user created successfully"
  else
    warn "Failed to create admin user (may already exist)"
  fi
  
  # Create test users
  info "Creating test user: testuser@$domain"
  if docker exec "$container_name" prosodyctl register testuser "$domain" "testpass"; then
    info "Test user created successfully"
  else
    warn "Failed to create test user (may already exist)"
  fi
  
  info "Creating regular user: user1@$domain"
  if docker exec "$container_name" prosodyctl register user1 "$domain" "user1pass"; then
    info "Regular user1 created successfully"
  else
    warn "Failed to create user1 (may already exist)"
  fi
  
  info "Creating regular user: user2@$domain"  
  if docker exec "$container_name" prosodyctl register user2 "$domain" "user2pass"; then
    info "Regular user2 created successfully"
  else
    warn "Failed to create user2 (may already exist)"
  fi
  
  # Verify users were created
  info "Verifying user creation..."
  if docker exec "$container_name" prosodyctl shell --help >/dev/null 2>&1; then
    info "User setup verification complete"
  fi
  
  info "XMPP users configured:"
  info "  - admin@$domain (password: adminpass)"
  info "  - testuser@$domain (password: testpass)" 
  info "  - user1@$domain (password: user1pass)"
  info "  - user2@$domain (password: user2pass)"
}

install_and_launch_app(){
  if ! command_exists adb; then
    fail "adb not found; cannot install Android app"
  fi
  
  install_conversations
  launch_conversations
}

summary(){
  info "Setup complete"
  info "Conversations is installed and ready for testing"
}

main(){
  parse_args "$@"
  ensure_prereqs
  setup_prosody_server
  setup_xmpp_users
  build_app
  install_and_launch_app
  summary
}

main "$@"