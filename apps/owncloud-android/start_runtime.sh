#!/usr/bin/env bash
# Environment + baseline setup script for OwnCloud CIAA tests.
# Steps:
#   1. Verify prerequisites (docker, python3, uv, adb)
#   2. Launch docker-compose stack (OwnCloud + DB + Redis)
#   3. Wait for container health
#   4. Create / reuse Python virtual environment via uv
#   5. Ensure Python deps (requests, python-dotenv) present if not declared already
#   6. Run seeder (produces baseline manifest)
#   7. Install Android app from: ./apk/<app-name>.apk (must exist before running)
#   8. Verify Frida Gadget listens on port 27042 (owned by com.owncloud.android)
set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}" )" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "owncloud-android" "$@")
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.yml"
SEED_SCRIPT="${SCRIPT_DIR}/owncloud_setup.py"
VENV_DIR="${SCRIPT_DIR}/.venv"
DEFAULT_OUTPUT="baseline_manifest.json"
SEED_OUTPUT=${SEED_OUTPUT:-$DEFAULT_OUTPUT}
HEALTH_TIMEOUT=${HEALTH_TIMEOUT:-180}
HEALTH_INTERVAL=5
LOG_PREFIX="[setup]"

TARGET_PACKAGE="com.owncloud.android"
TARGET_DIR="/data/data/${TARGET_PACKAGE}"
ANDROID_BASELINE_FILE="${SCRIPT_DIR}/baseline_android_dir.txt"

# Defaults
FRIDA_PORT=${FRIDA_PORT:-27042}

info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*" >&2; }
fail(){ printf '%s[error] %s\n' "$LOG_PREFIX" "$*" >&2; exit 1; }
command_exists(){ command -v "$1" >/dev/null 2>&1; }

ensure_uv(){
  if command_exists uv; then return 0; fi
  warn "uv not found; installing (https://astral.sh/uv)"
  command_exists curl || fail "curl required to install uv"
  curl -Ls https://astral.sh/uv/install.sh | sh || fail "uv install failed"
  export PATH="$HOME/.local/bin:$PATH"
  command_exists uv || fail "uv not found after install"
}

ensure_prereqs(){
  info "Checking prerequisites"
  command_exists docker || fail "docker is required"
  command_exists python3 || fail "python3 is required"
  command_exists adb || fail "adb is required"
  ensure_uv
  info "Prerequisites OK"
}

start_stack(){
  info "Starting docker stack"
  docker compose -f "$COMPOSE_FILE" up -d --remove-orphans
}

ensure_oauth2_enabled(){
  info "Ensuring oauth2 server app is enabled"
  if docker exec owncloud_server occ app:enable oauth2 >/dev/null 2>&1; then
    info "oauth2 app enabled"
  else
    fail "Failed to enable oauth2 app; check server logs"
  fi
}

wait_for_health(){
  info "Waiting for owncloud_server health (timeout ${HEALTH_TIMEOUT}s)"
  local start; start=$(date +%s)
  while true; do
    local status; status=$(docker inspect --format '{{.State.Health.Status}}' owncloud_server 2>/dev/null || echo "unknown")
    if [[ "$status" == "healthy" ]]; then
      info "ownCloud container healthy"
      break
    fi
    local now; now=$(date +%s)
    if (( now - start > HEALTH_TIMEOUT )); then
      docker ps --format 'table {{.Names}}\t{{.Status}}'
      fail "Timed out waiting for owncloud_server (last status: $status)"
    fi
    sleep "$HEALTH_INTERVAL"
  done
}

setup_python(){
  info "Setting up Python environment via uv"
  cd "$SCRIPT_DIR"
  if [[ ! -d "$VENV_DIR" ]]; then
    uv venv "$VENV_DIR"
  fi
  # shellcheck source=/dev/null
  source "$VENV_DIR/bin/activate"
  if [[ -f uv.lock ]]; then
    uv sync --frozen || fail "uv sync failed"
  elif [[ -f pyproject.toml ]]; then
    # Install declared project + extras
    uv pip install -e . || true
  fi
  ensure_python_deps
  info "Python environment ready"
}

ensure_python_deps(){
  # Minimal deps needed by seeder if not already resolved via pyproject/lock
  local pkgs=(requests python-dotenv)
  for p in "${pkgs[@]}"; do
    python -c "import $p" 2>/dev/null || uv pip install "$p" >/dev/null 2>&1 || fail "Failed installing $p"
  done
}

run_seeder(){
  info "Running seeding script -> $SEED_OUTPUT"
  cd "$SCRIPT_DIR"
  # shellcheck source=/dev/null
  source "$VENV_DIR/bin/activate"
  SEED_OUTPUT_FILE="$SEED_OUTPUT" python3 "$SEED_SCRIPT" || fail "Seeding failed"
  if [[ ! -f "$SEED_OUTPUT" ]]; then
    fail "Expected manifest $SEED_OUTPUT not found"
  fi
  info "Seeder produced $(ls -l "$SEED_OUTPUT" | awk '{print $5" bytes"}')"
}

install_app(){
  info "Installing ownCloud on Android device"
  adb uninstall com.owncloud.android >/dev/null 2>&1 || true
  adb_install_apk "$APK_PATH"

  info "Launching ownCloud..."
  adb shell am start -n com.owncloud.android/com.owncloud.android.ui.activity.SplashActivity >/dev/null 2>&1 || true
  sleep 2
}

check_frida_gadget(){
  local port="$FRIDA_PORT"
  info "Checking Frida Gadget status on device (port ${port})"
  # Ensure a device is connected
  adb wait-for-device >/dev/null 2>&1 || true
  if ! adb get-state >/dev/null 2>&1; then
    fail "No adb device detected; cannot perform Frida check"
  fi

  if ! adb shell su 0 id >/dev/null 2>&1; then
    fail "root not available on device; root required for Frida check"
  fi

  local out
  out=$(adb shell su 0 netstat -tulpn 2>/dev/null) || out=""
  out=$(printf "%s" "$out" | tr -d '\r')
  if [[ -z "$out" ]]; then
    fail "Could not retrieve socket list from device under su"
  fi
  local line
  line=$(printf "%s\n" "$out" | grep -E "LISTEN" | grep -E "[:\.]${port}\b" | head -1 || true)
  if [[ -n "$line" ]]; then
    if printf "%s" "$line" | grep -q "com.owncloud.android"; then
      info "Frida Gadget listening on ${port}. Frida Gadget Injection Successful"
    else
      info "Listener detected on ${port}: $line"
      warn "Port owner not com.owncloud.android; Frida Gadget may not be injected properly"
    fi
  else
    warn "No listener found on port ${port}; Frida Gadget is not be running"
  fi
}

capture_android_dir_baseline(){
  info "Capturing Android directory baseline -> $ANDROID_BASELINE_FILE"
  adb shell su 0 find "$TARGET_DIR" 2>/dev/null \
    | tr -d '\r' \
    | LC_ALL=C sort -u > "$ANDROID_BASELINE_FILE" || warn "Unable to capture Android baseline"
}

summary(){
  info "Setup complete"
  info "Manifest: $SEED_OUTPUT"
  if [[ -f "$ANDROID_BASELINE_FILE" ]]; then
    info "Android baseline: $ANDROID_BASELINE_FILE ($(wc -l < "$ANDROID_BASELINE_FILE") lines)"
  else
    warn "Android baseline not found at $ANDROID_BASELINE_FILE. The adb pull may have failed."
  fi
}

main(){
  ensure_prereqs
  start_stack
  wait_for_health
  ensure_oauth2_enabled
  setup_python
  run_seeder
  install_app
  check_frida_gadget
  capture_android_dir_baseline
  summary
}

main "$@"
