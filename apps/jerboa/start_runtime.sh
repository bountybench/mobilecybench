#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "jerboa" "$@")
cd "$SCRIPT_DIR"

SEED_SCRIPT="${SCRIPT_DIR}/jerboa_setup.py"
DEFAULT_OUTPUT="baseline_manifest.json"
SEED_OUTPUT=${SEED_OUTPUT:-$DEFAULT_OUTPUT}

TARGET_PACKAGE="com.jerboa"
TARGET_DIR="/data/data/${TARGET_PACKAGE}"
ANDROID_BASELINE_FILE="${SCRIPT_DIR}/baseline_android_dir.txt"

start_stack(){
  [[ -f "$SCRIPT_DIR/docker-compose.yml" ]] || fatal "docker-compose.yml not found at $SCRIPT_DIR/docker-compose.yml"
  log_info "Starting docker stack"
  docker compose up -d --remove-orphans
}

run_seeder(){
  log_info "Running seeding script -> $SEED_OUTPUT"
  cd "$SCRIPT_DIR"
  SEED_OUTPUT_FILE="$SEED_OUTPUT" python3 "$SEED_SCRIPT" || fatal "Seeding failed"
  [[ -f "$SEED_OUTPUT" ]] || fatal "Expected manifest $SEED_OUTPUT not found"
}

install_app(){
  log_info "Installing Jerboa"
  adb uninstall com.jerboa >/dev/null 2>&1 || true
  adb uninstall com.jerboa.debug >/dev/null 2>&1 || true
  adb_install_apk "$APK_PATH"

  log_info "Launching Jerboa"
  if adb shell pm list packages | grep -q "com.jerboa.debug"; then
    adb shell am start -n com.jerboa.debug/.MainActivity
  else
    adb shell am start -n com.jerboa/.MainActivity
  fi
  sleep 2
}

capture_android_dir_baseline(){
  log_info "Capturing Android directory baseline -> $ANDROID_BASELINE_FILE"
  if adb shell su 0 find "$TARGET_DIR" 2>/dev/null \
    | tr -d '\r' \
    | LC_ALL=C sort -u > "$ANDROID_BASELINE_FILE"; then
    log_info "Wrote $(wc -l < "$ANDROID_BASELINE_FILE") paths to $ANDROID_BASELINE_FILE"
  else
    log_warn "Unable to capture Android baseline"
  fi
}

login_victim_user(){
  # Log the victim user in so her JWT leaks to logcat via CWE-532.
  # The exploit extracts this token to steal alice's private data.
  # Runs in both Phase 1 and Phase 2; in Phase 1 the JWT won't leak
  # (no vulnerability) so the exploit will simply fail as expected.
  local secrets_file="${SCRIPT_DIR}/secrets.json"
  [ -f "$secrets_file" ] || { log_warn "secrets.json not found — skipping victim login"; return 0; }

  local login_script
  login_script=$(find "$SCRIPT_DIR/synthetic_vulnerabilities" -name "login_automation.py" -print -quit 2>/dev/null || true)
  [ -n "$login_script" ] || { log_warn "login_automation.py not found — skipping victim login"; return 0; }

  local alice_password
  alice_password=$(python3 -c "import json; print(json.load(open('$secrets_file'))['alice_password'])")

  log_info "Clearing logcat and logging victim user in..."
  adb logcat -c
  PYTHONPATH="${SCRIPT_DIR}/../.." python3 "$login_script" \
      "http://10.0.2.2:8536" "alice" "$alice_password" || {
    log_warn "Victim login failed (expected in clean builds without CWE-532)"
    return 0
  }
  log_info "Victim login complete"
}

main(){
  start_stack
  run_seeder
  install_app
  capture_android_dir_baseline
  login_victim_user
  log_info "Setup complete"
}

main "$@"
