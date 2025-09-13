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

build_app(){
  if [[ "$SKIP_BUILD" == "true" ]]; then
    info "Skipping build (--fast mode)"
    return 0
  fi

  info "Building Jellyfin from source"
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

install_jellyfin(){
  info "Installing Jellyfin on Android device"
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
  local apk_dir="$CODEBASE_DIR/app/build/outputs/apk/libre/release"

  # Try architecture-specific signed APK first
  apk=$(find "$apk_dir" -name "*-$arch-release.apk" -not -name "*unsigned*" -type f 2>/dev/null | head -1)

  if [[ -z "$apk" ]]; then
    warn "No signed $arch APK found, trying any signed APK"
    apk=$(find "$apk_dir" -name "*-release.apk" -not -name "*unsigned*" -type f 2>/dev/null | head -1)
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
    info "Jellyfin installed successfully"
  else
    fail "Failed to install APK via ADB. Check device connection and APK integrity."
  fi
}

launch_jellyfin() {
    info "Launching Jellyfin..."

    # Launch the app using the package manager
    if adb shell pm list packages | grep -q "$TARGET_PACKAGE"; then
        info "Launching Jellyfin"
        # Use monkey to launch the app instead of direct activity launch
        adb shell monkey -p "$TARGET_PACKAGE" -c android.intent.category.LAUNCHER 1
    else
        fail "Jellyfin package not found"
    fi

    sleep $LAUNCH_SLEEP

    # Verify the app is running
    if adb shell dumpsys window | grep -q "mCurrentFocus.*$TARGET_PACKAGE"; then
        info "Jellyfin launched successfully"
    else
        warn "Jellyfin may not have launched properly (focus not detected)."
    fi
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

  # Check if initial setup is needed
  info "Checking if initial setup is required..."
  startup_response=$(curl -s "$jellyfin_url/Startup/Configuration" 2>/dev/null || echo "")

  if echo "$startup_response" | grep -q '"UICulture"'; then
    info "Creating admin user: $admin_username"

    # Create the initial admin user
    curl -X POST "$jellyfin_url/Startup/User" \
      -H "Content-Type: application/json" \
      -d "{\"Name\":\"$admin_username\",\"Password\":\"$admin_password\"}" \
      >/dev/null 2>&1

    # Complete the startup wizard
    curl -X POST "$jellyfin_url/Startup/Complete" >/dev/null 2>&1

    info "Jellyfin admin user created successfully"
    info "Admin credentials: $admin_username / $admin_password"
  else
    info "Jellyfin already configured or startup wizard not available"
  fi
}

install_and_launch_app(){
  if ! command_exists adb; then
    fail "adb not found; cannot install Android app"
  fi

  install_jellyfin
  launch_jellyfin
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
  build_app
  install_and_launch_app
  summary
}

main "$@"
