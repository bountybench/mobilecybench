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
# Usage:
#   ./setup.sh
#   SEED_OUTPUT=my_manifest.json ./setup.sh
set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}" )" && pwd)"
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

parse_args(){
  if [[ $# -gt 0 ]]; then
    warn "Arguments are no longer supported. Ignoring: $*"
  fi
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
  command_exists python || fail "python is required"
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
  source "$VENV_DIR/Scripts/activate"
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
  source "$VENV_DIR/Scripts/activate"
  SEED_OUTPUT_FILE="$SEED_OUTPUT" python "$SEED_SCRIPT" || fail "Seeding failed"
  if [[ ! -f "$SEED_OUTPUT" ]]; then
    fail "Expected manifest $SEED_OUTPUT not found"
  fi
  info "Seeder produced $(ls -l "$SEED_OUTPUT" | awk '{print $5" bytes"}')"
}

install_owncloud(){
  info "Installing ownCloud on Android device from local APK folder"
  adb wait-for-device
  if ! adb get-state >/dev/null 2>&1; then
    fail "No adb device detected; ensure an emulator/device is running"
  fi

  local apk_dir apk
  apk_dir="${SCRIPT_DIR}/apk"
  if [[ ! -d "$apk_dir" ]]; then
    fail "APK folder not found at $apk_dir. Place your app-name.apk there and re-run."
  fi

  # Pick the newest .apk in the folder (though ideally there should only be one)
  apk=$(ls -1t "$apk_dir"/*.apk 2>/dev/null | head -n 1 || true)
  if [[ -z "$apk" ]]; then
    fail "No .apk found in $apk_dir. Place your app-name.apk there and re-run."
  fi

  info "Using APK: $(basename "$apk")"

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
  if install_output=$(adb install -r "$apk" 2>&1); then
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
  install_owncloud
  launch_owncloud
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
