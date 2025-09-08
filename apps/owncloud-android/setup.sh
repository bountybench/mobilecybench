#!/usr/bin/env bash
# Environment + baseline setup script for OwnCloud CIAA tests.
# Steps:
#   1. Verify prerequisites (docker, python3, uv, adb)
#   2. Launch docker-compose stack (OwnCloud + DB + Redis)
#   3. Wait for container health
#   4. Create / reuse Python virtual environment via uv
#   5. Ensure Python deps (requests, python-dotenv) present if not declared already
#   6. Run seeder (produces baseline manifest)
#   7. Install Android app 
#        - By default: build from source and install (setup_app_source.sh)
#        - With --fast or FAST=1: install via APK link (setup_app_apklink.sh)
#   8. Verify Frida Gadget listens on port 27042 (owned by com.owncloud.android)
# Usage:
#   ./setup.sh [--fast] [--apk-url URL]
#   FAST=1 ./setup.sh                    # Fast path (APK link)
#   SEED_OUTPUT=my_manifest.json ./setup.sh
set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}" )" && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.yml"
SEED_SCRIPT="${SCRIPT_DIR}/owncloud_setup.py"
APK_LINK_SCRIPT="${SCRIPT_DIR}/setup_app_apklink.sh"
APP_SOURCE_SCRIPT="${SCRIPT_DIR}/setup_app_source.sh"
VENV_DIR="${SCRIPT_DIR}/.venv"
CODEBASE_DIR="${SCRIPT_DIR}/codebase"
DEFAULT_OUTPUT="baseline_manifest.json"
SEED_OUTPUT=${SEED_OUTPUT:-$DEFAULT_OUTPUT}
HEALTH_TIMEOUT=${HEALTH_TIMEOUT:-180}
HEALTH_INTERVAL=5
LOG_PREFIX="[setup]"

TARGET_PACKAGE="com.owncloud.android"
TARGET_DIR="/data/data/${TARGET_PACKAGE}"
ANDROID_BASELINE_FILE="${SCRIPT_DIR}/baseline_android_dir.txt"

# Defaults and CLI flags
INSTALL_MODE="source"   # source | apk
APK_URL="${APK_URL:-}"
FRIDA_PORT=${FRIDA_PORT:-27042}

parse_args(){
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --fast|-f)
        INSTALL_MODE="apk"
        shift
        ;;
      --apk-url)
        APK_URL="${2:-}"
        if [[ -z "$APK_URL" ]]; then fail "--apk-url requires a value"; fi
        shift 2
        ;;
      --help|-h)
        cat <<EOF
Usage: ./setup.sh [--fast] [--apk-url URL]
  --fast, -f      Use APK link install instead of building from source
  --apk-url URL   Custom APK URL for fast mode (overrides default)

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
  if [[ "${FAST:-0}" == "1" ]]; then INSTALL_MODE="apk"; fi
}

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

compose(){
  if command_exists docker && docker compose version >/dev/null 2>&1; then
    docker compose -f "$COMPOSE_FILE" "$@"
  elif command_exists docker-compose; then
    docker-compose -f "$COMPOSE_FILE" "$@"
  else
    fail "docker compose plugin not available"
  fi
}

start_stack(){
  [[ -f "$COMPOSE_FILE" ]] || fail "docker-compose.yml not found at $COMPOSE_FILE"
  info "Starting docker stack"
  compose up -d --remove-orphans
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

install_owncloud(){
  info "Installing ownCloud on Android device from source-built artifact"
  adb wait-for-device
  if ! adb get-state >/dev/null 2>&1; then
    fail "No adb device detected; ensure emulator is running"
  fi

  if [[ ! -d "$CODEBASE_DIR" ]]; then
    fail "Codebase not found at $CODEBASE_DIR"
  fi

  local apk
  apk=$(find "$CODEBASE_DIR/owncloudApp/build/outputs/apk/original/release/" -name "*-original-release.apk" -type f 2>/dev/null | head -1)

  if [[ -z "$apk" ]]; then
    fail "Could not find built APK. IMPORTANT: Run $APP_SOURCE_SCRIPT before launching the emulator."
  fi

  info "Found APK: $(basename "$apk")"

  # Uninstall existing versions
  info "Uninstalling previous packages (if installed)"
  adb uninstall com.owncloud.android >/dev/null 2>&1 || true
  adb uninstall com.owncloud.android.debug >/dev/null 2>&1 || true

  info "Installing APK: $apk"
  
  # Add debugging information for CI troubleshooting
  info "Device info for debugging:"
  info "- SDK level: $(adb shell getprop ro.build.version.sdk 2>/dev/null | tr -d '\r' || echo 'unknown')"
  info "- CPU ABI: $(adb shell getprop ro.product.cpu.abi 2>/dev/null | tr -d '\r' || echo 'unknown')"
  info "- Device model: $(adb shell getprop ro.product.model 2>/dev/null | tr -d '\r' || echo 'unknown')"
  
  # Check APK info if aapt is available
  if command -v aapt >/dev/null 2>&1; then
    info "APK info: $(aapt dump badging "$apk" 2>/dev/null | grep -E '(package:|native-code:)' | head -2 || echo 'aapt info unavailable')"
  fi
  
  # Try installation with verbose output for debugging
  info "Attempting installation with detailed error output..."
  local install_output
  if install_output=$(adb install "$apk" 2>&1); then
    info "OwnCloud installed successfully"
    info "Install output: $install_output"
  else
    fail "Failed to install APK via ADB. Error: $install_output"
  fi
}

launch_owncloud() {
    info "Launching ownCloud..."
    
    # Launch the app
    if adb shell pm list packages | grep -q "com.owncloud.android" && ! adb shell pm list packages | grep -q "com.owncloud.android.debug"; then
        info "Launching release version"
        adb shell am start -n com.owncloud.android/com.owncloud.android.ui.activity.SplashActivity
        PACKAGE_NAME="com.owncloud.android"
    elif adb shell pm list packages | grep -q "com.owncloud.android.debug"; then
        info "Launching debug version"
        adb shell am start -n com.owncloud.android.debug/com.owncloud.android.ui.activity.SplashActivity
        PACKAGE_NAME="com.owncloud.android.debug"
    else
        error "No ownCloud package found"
    fi
    
    sleep 1
    
    # Verify the app is running by checking if the process exists
    if adb shell pidof "$PACKAGE_NAME" >/dev/null 2>&1; then
        info "ownCloud launched successfully (process running)"
    else
        warn "ownCloud may not have launched properly (process not found)."
    fi
}

install_app(){
  if ! command_exists adb; then
    fail "adb not found; cannot install Android app"
  fi
  case "$INSTALL_MODE" in
    source)
      # Expect APK to be already built by setup_app_source.sh (pre-emulator)
      install_owncloud
      launch_owncloud
      ;;
    apk)
      if [[ -x "$APK_LINK_SCRIPT" ]]; then
        info "Installing app via APK link (--fast)"
        if [[ -n "$APK_URL" ]]; then
          "$APK_LINK_SCRIPT" "$APK_URL" || fail "APK link install script failed"
        else
          "$APK_LINK_SCRIPT" || fail "APK link install script failed"
        fi
      else
        fail "APK link script missing or not executable: $APK_LINK_SCRIPT"
      fi
      ;;
    *)
      fail "Unknown INSTALL_MODE=$INSTALL_MODE"
      ;;
  esac
  # Basic verification
  sleep 2
  if adb shell pm list packages | grep -q "com.owncloud.android"; then
    info "Android app installed (com.owncloud.android)"
  else
    fail "Android app installation not verified"
  fi
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
  if ! command_exists adb; then
    warn "adb not found; skipping Android baseline capture"
    return 0
  fi
  info "Capturing Android directory baseline -> $ANDROID_BASELINE_FILE"
  # Ensure a device is connected and ready
  adb wait-for-device >/dev/null 2>&1 || true
  if ! adb get-state >/dev/null 2>&1; then
    warn "No adb device detected; skipping Android baseline capture"
    return 0
  fi
  # Get directory listing
  if adb shell 'command -v su >/dev/null 2>&1' >/dev/null 2>&1; then
    if adb shell su 0 find "$TARGET_DIR" 2>/dev/null \
      | tr -d '\r' \
      | LC_ALL=C sort -u > "$ANDROID_BASELINE_FILE"; then
      info "Wrote $(wc -l < "$ANDROID_BASELINE_FILE") paths to $ANDROID_BASELINE_FILE"
      return 0
    else
      warn "su 0 find failed"
    fi
  fi
  warn "Unable to capture Android baseline"
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
  parse_args "$@"
  ensure_prereqs
  start_stack
  wait_for_health
  setup_python
  run_seeder
  install_app
  check_frida_gadget
  capture_android_dir_baseline
  summary
}

main "$@"
