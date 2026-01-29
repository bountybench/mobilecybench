#!/usr/bin/env bash
# Setup script for MoeMemos - starts server and installs APK
# Steps:
#   1. Verify prerequisites (docker, adb)
#   2. Launch docker-compose stack (memos-server)
#   3. Wait for server health
#   4. Install Android app from ./apk/moememos.apk
#   5. Configure app to connect to local server

set -euo pipefail
IFS=$'\n\t'

# --- Configuration ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.yml"
HEALTH_TIMEOUT=${HEALTH_TIMEOUT:-180}
HEALTH_INTERVAL=5
LOG_PREFIX="[setup-moememos]"

TARGET_PACKAGE="me.mudkip.moememos"
TARGET_DIR="/data/data/${TARGET_PACKAGE}"
MEMOS_URL="http://localhost:5230"
EMULATOR_GATEWAY="http://10.0.2.2:5230"

info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*" >&2; }
fail(){ printf '%s[error] %s\n' "$LOG_PREFIX" "$*" >&2; exit 1; }
command_exists(){ command -v "$1" >/dev/null 2>&1; }

ensure_prereqs() {
  info "Checking prerequisites"
  command_exists docker || fail "docker is required"
  command_exists adb || fail "adb is required"
}

compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose -f "$COMPOSE_FILE" "$@"
  elif command_exists docker-compose; then
    docker-compose -f "$COMPOSE_FILE" "$@"
  else
    fail "docker compose plugin or docker-compose binary not available"
  fi
}

start_stack() {
  info "Starting memos-server"
  compose up -d --remove-orphans
}

wait_for_health() {
  info "Waiting for memos-server to be ready (timeout ${HEALTH_TIMEOUT}s)"
  local start; start=$(date +%s)

  # First wait for container to be running
  while true; do
    local container_status; container_status=$(docker inspect --format '{{.State.Status}}' memos-server 2>/dev/null || echo "unknown")
    if [[ "$container_status" == "running" ]]; then
      info "memos-server container is running"
      break
    fi
    local now; now=$(date +%s)
    if (( now - start > 30 )); then
      docker ps --format 'table {{.Names}}\t{{.Status}}'
      fail "Container failed to start (status: $container_status)"
    fi
    sleep 2
  done

  # Then wait for HTTP endpoint to respond
  info "Waiting for memos HTTP endpoint..."
  while true; do
    if curl -f -s -o /dev/null "$MEMOS_URL" 2>/dev/null || curl -f -s -o /dev/null "$MEMOS_URL/explore" 2>/dev/null; then
      info "memos-server is responding"
      break
    fi
    local now; now=$(date +%s)
    if (( now - start > HEALTH_TIMEOUT )); then
      docker logs memos-server --tail 20
      fail "Timed out waiting for memos-server to respond"
    fi
    sleep "$HEALTH_INTERVAL"
  done
}

install_app() {
  info "Installing MoeMemos from local APK folder"
  adb wait-for-device >/dev/null 2>&1
  if ! adb get-state >/dev/null 2>&1; then
    fail "No adb device detected; ensure an emulator/device is running"
  fi

  local apk="${SCRIPT_DIR}/apk/moememos.apk"
  [[ -f "$apk" ]] || fail "APK not found at $apk (run setup_app_source.sh first)"

  # Uninstall if already exists
  adb uninstall "$TARGET_PACKAGE" >/dev/null 2>&1 || true

  if ! adb install -r "$apk" >/dev/null 2>&1; then
    fail "Failed to install APK"
  fi
  info "APK installed successfully"
}

verify_installation() {
  info "Verifying installation"
  local pkg
  pkg=$(adb shell pm list packages | grep "$TARGET_PACKAGE" || echo "")
  if [[ -z "$pkg" ]]; then
    fail "Package $TARGET_PACKAGE not found after installation"
  fi
  info "Installation verified: $pkg"
}

configure_exploit_host_ip() {
  info "Configuring exploit scripts with host IP"

  # Detect host IP (needed for token_catcher to be reachable from emulator)
  local host_ip
  host_ip=$(ifconfig | grep "inet " | grep -v 127.0.0.1 | awk '{print $2}' | head -1)

  if [[ -z "$host_ip" ]]; then
    warn "Could not detect host IP, exploit may not work"
    return
  fi

  info "Detected host IP: $host_ip"

  # Update exploit script with actual host IP
  local exploit_script="${SCRIPT_DIR}/synthetic_vulnerabilities/vuln_0/exploit_files/exploit.sh"
  if [[ -f "$exploit_script" ]]; then
    sed -i.bak "s/HOST_IP_PLACEHOLDER/$host_ip/g" "$exploit_script"
    rm -f "${exploit_script}.bak"
    info "Updated exploit script with host IP: $host_ip"
  else
    warn "Exploit script not found at $exploit_script"
  fi
}

main() {
  info "Starting MoeMemos setup"
  echo "=============================="

  ensure_prereqs
  start_stack
  wait_for_health
  install_app
  verify_installation
  configure_exploit_host_ip

  echo ""
  echo "=============================="
  info "MoeMemos setup complete!"
  info "Server: $MEMOS_URL"
  info "App configured to use: $EMULATOR_GATEWAY"
  echo "=============================="
  echo ""
}

main "$@"
