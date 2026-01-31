#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "owncloud-android" "$@")
cd "$SCRIPT_DIR"

SEED_SCRIPT="${SCRIPT_DIR}/owncloud_setup.py"
VENV_DIR="${SCRIPT_DIR}/.venv"
DEFAULT_OUTPUT="baseline_manifest.json"
SEED_OUTPUT=${SEED_OUTPUT:-$DEFAULT_OUTPUT}
HEALTH_TIMEOUT=${HEALTH_TIMEOUT:-180}
HEALTH_INTERVAL=5

TARGET_PACKAGE="com.owncloud.android"
TARGET_DIR="/data/data/${TARGET_PACKAGE}"
ANDROID_BASELINE_FILE="${SCRIPT_DIR}/baseline_android_dir.txt"

FRIDA_PORT=${FRIDA_PORT:-27042}

ensure_uv(){
  if command -v uv >/dev/null 2>&1; then return 0; fi
  log_warn "uv not found; installing (https://astral.sh/uv)"
  command -v curl >/dev/null 2>&1 || fatal "curl required to install uv"
  curl -Ls https://astral.sh/uv/install.sh | sh || fatal "uv install failed"
  export PATH="$HOME/.local/bin:$PATH"
  command -v uv >/dev/null 2>&1 || fatal "uv not found after install"
}

ensure_prereqs(){
  log_info "Checking prerequisites"
  command -v python3 >/dev/null 2>&1 || fatal "python3 is required"
  command -v adb >/dev/null 2>&1 || fatal "adb is required"
  ensure_uv
  log_info "Prerequisites OK"
}

start_stack(){
  log_info "Starting docker stack"
  docker compose up -d --remove-orphans
}

ensure_oauth2_enabled(){
  log_info "Ensuring oauth2 server app is enabled"
  if docker exec owncloud_server occ app:enable oauth2 >/dev/null 2>&1; then
    log_info "oauth2 app enabled"
  else
    fatal "Failed to enable oauth2 app; check server logs"
  fi
}

wait_for_health(){
  wait_healthy owncloud_server "$HEALTH_TIMEOUT" || fatal "owncloud_server did not become healthy"
}

setup_python(){
  log_info "Setting up Python environment via uv"
  cd "$SCRIPT_DIR"
  if [[ ! -d "$VENV_DIR" ]]; then
    uv venv "$VENV_DIR"
  fi
  # shellcheck source=/dev/null
  source "$VENV_DIR/bin/activate"
  if [[ -f uv.lock ]]; then
    uv sync --frozen || fatal "uv sync failed"
  elif [[ -f pyproject.toml ]]; then
    uv pip install -e . || true
  fi
  ensure_python_deps
  log_info "Python environment ready"
}

ensure_python_deps(){
  local pkgs=(requests python-dotenv)
  for p in "${pkgs[@]}"; do
    python -c "import $p" 2>/dev/null || uv pip install "$p" >/dev/null 2>&1 || fatal "Failed installing $p"
  done
}

run_seeder(){
  log_info "Running seeding script -> $SEED_OUTPUT"
  cd "$SCRIPT_DIR"
  # shellcheck source=/dev/null
  source "$VENV_DIR/bin/activate"
  SEED_OUTPUT_FILE="$SEED_OUTPUT" python3 "$SEED_SCRIPT" || fatal "Seeding failed"
  if [[ ! -f "$SEED_OUTPUT" ]]; then
    fatal "Expected manifest $SEED_OUTPUT not found"
  fi
  log_info "Seeder produced $(ls -l "$SEED_OUTPUT" | awk '{print $5" bytes"}')"
}

install_app(){
  log_info "Installing ownCloud on Android device"
  adb uninstall com.owncloud.android >/dev/null 2>&1 || true
  adb_install_apk "$APK_PATH"

  log_info "Launching ownCloud..."
  adb shell am start -n com.owncloud.android/com.owncloud.android.ui.activity.SplashActivity >/dev/null 2>&1 || true
  sleep 2
}

check_frida_gadget(){
  local port="$FRIDA_PORT"
  log_info "Checking Frida Gadget status on device (port ${port})"
  adb wait-for-device >/dev/null 2>&1 || true
  if ! adb get-state >/dev/null 2>&1; then
    fatal "No adb device detected; cannot perform Frida check"
  fi

  if ! adb shell su 0 id >/dev/null 2>&1; then
    fatal "root not available on device; root required for Frida check"
  fi

  local out
  out=$(adb shell su 0 netstat -tulpn 2>/dev/null) || out=""
  out=$(printf "%s" "$out" | tr -d '\r')
  if [[ -z "$out" ]]; then
    fatal "Could not retrieve socket list from device under su"
  fi
  local line
  line=$(printf "%s\n" "$out" | grep -E "LISTEN" | grep -E "[:\.]${port}\b" | head -1 || true)
  if [[ -n "$line" ]]; then
    if printf "%s" "$line" | grep -q "com.owncloud.android"; then
      log_info "Frida Gadget listening on ${port}. Frida Gadget Injection Successful"
    else
      log_info "Listener detected on ${port}: $line"
      log_warn "Port owner not com.owncloud.android; Frida Gadget may not be injected properly"
    fi
  else
    log_warn "No listener found on port ${port}; Frida Gadget is not be running"
  fi
}

capture_android_dir_baseline(){
  log_info "Capturing Android directory baseline -> $ANDROID_BASELINE_FILE"
  adb shell su 0 find "$TARGET_DIR" 2>/dev/null \
    | tr -d '\r' \
    | LC_ALL=C sort -u > "$ANDROID_BASELINE_FILE" || log_warn "Unable to capture Android baseline"
}

summary(){
  log_info "Setup complete"
  log_info "Manifest: $SEED_OUTPUT"
  if [[ -f "$ANDROID_BASELINE_FILE" ]]; then
    log_info "Android baseline: $ANDROID_BASELINE_FILE ($(wc -l < "$ANDROID_BASELINE_FILE") lines)"
  else
    log_warn "Android baseline not found at $ANDROID_BASELINE_FILE. The adb pull may have failed."
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
