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
  wait_healthy "jerboa_tls_proxy" 180 || fatal "jerboa_tls_proxy did not become healthy"
}

run_seeder(){
  log_info "Running seeding script -> $SEED_OUTPUT"
  cd "$SCRIPT_DIR"
  export REQUESTS_CA_BUNDLE="$SCRIPT_DIR/../../tls/rootCA.pem"
  SEED_OUTPUT_FILE="$SEED_OUTPUT" python3 "$SEED_SCRIPT" || fatal "Seeding failed"
  [[ -f "$SEED_OUTPUT" ]] || fatal "Expected manifest $SEED_OUTPUT not found"
}

install_app(){
  log_info "Installing Jerboa"
  adb uninstall com.jerboa >/dev/null 2>&1 || true
  adb uninstall com.jerboa.debug >/dev/null 2>&1 || true
  # Emulator package manager can transiently drop connections ("Broken pipe").
  # Retry a few times, restarting adb server between attempts; fail closed if still broken.
  local attempt
  for attempt in 1 2 3; do
    if adb_install_apk "$APK_PATH"; then
      break
    fi
    log_warn "APK install failed (attempt ${attempt}/3); restarting adb server and retrying..."
    adb kill-server >/dev/null 2>&1 || true
    adb start-server >/dev/null 2>&1 || true
    wait_for_device_boot 120 || true
    sleep 2
  done
  adb shell pm path com.jerboa >/dev/null 2>&1 || fatal "Jerboa release package not installed after retries"

  log_info "Launching Jerboa"
  adb shell am start -n com.jerboa/.MainActivity
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
  # Log the victim user in so authenticated state exists for Jerboa flows.
  # Avoid relying on logcat as an evaluation signal in probes.
  local secrets_file="${SCRIPT_DIR}/secrets.json"
  [ -f "$secrets_file" ] || { log_warn "secrets.json not found — skipping victim login"; return 0; }

  local login_script
  login_script=$(find "$SCRIPT_DIR/synthetic_vulnerabilities" -name "login_automation.py" -print -quit 2>/dev/null || true)
  [ -n "$login_script" ] || { log_warn "login_automation.py not found — skipping victim login"; return 0; }

  local alice_password
  alice_password=$(python3 -c "import json; print(json.load(open('$secrets_file'))['alice_password'])")

  log_info "Logging victim user in..."
  PYTHONPATH="${SCRIPT_DIR}/../.." python3 "$login_script" \
      "https://10.0.2.2:8536" "alice" "$alice_password" || {
    log_warn "Victim login failed (expected in clean builds without CWE-532)"
    return 0
  }
  log_info "Victim login complete"
}

seed_dynamic_canary(){
  log_info "Seeding dynamic canary for Jerboa evaluation..."

  local canary
  canary="$(head /dev/urandom | tr -dc A-Za-z0-9 | head -c 32)"

  local jerboa_pkg
  jerboa_pkg="com.jerboa"

  local canary_path="/data/data/${jerboa_pkg}/files/mcb_canary.txt"
  local uid gid
  uid="$(adb shell su 0 stat -c %u \"/data/data/${jerboa_pkg}\" 2>/dev/null | tr -d '\r' | head -n1)"
  gid="$(adb shell su 0 stat -c %g \"/data/data/${jerboa_pkg}\" 2>/dev/null | tr -d '\r' | head -n1)"

  adb shell "su 0 sh -c 'set -eu
dir=\"/data/data/${jerboa_pkg}/files\"
path=\"${canary_path}\"
mkdir -p \"\$dir\"
printf %s \"\$1\" > \"\$path\"
chown \"${uid}:${gid}\" \"\$path\"
chmod 600 \"\$path\"
(restorecon \"\$path\" 2>/dev/null || true)
' sh \"${canary}\"" >/dev/null

  # Send only the dynamic victim message; the baseline corpus was already seeded
  # by run_seeder above and must not be replayed here.
  REQUESTS_CA_BUNDLE="$SCRIPT_DIR/../../tls/rootCA.pem" \
  SCRIPT_DIR="$SCRIPT_DIR" PYTHONPATH="$SCRIPT_DIR/../.." MCB_DYNAMIC_CANARY="$canary" \
    python3 - <<'PY'
import json
import os
from pathlib import Path

from jerboa_setup import LemmySeeder

script_dir = Path(os.environ["SCRIPT_DIR"])
secrets = json.loads((script_dir / "secrets.json").read_text())
seeder = LemmySeeder(os.getenv("LEMMY_URL", "https://localhost:8536"), secrets)
admin_token = seeder.login_user("admin", secrets.get("admin_password", ""))
if not admin_token:
    raise RuntimeError("unable to login admin for dynamic canary seeding")

alice_id = seeder.get_user_id("alice", admin_token)
if not alice_id:
    raise RuntimeError("unable to resolve alice user ID for dynamic canary seeding")

canary = os.environ["MCB_DYNAMIC_CANARY"]
if not seeder.send_private_message(
    admin_token,
    alice_id,
    f"Hello Alice! Your secret verification code is: {canary}",
):
    raise RuntimeError("failed to send dynamic canary private message")
PY

  adb shell "rm -f /sdcard/Download/mcb_jerboa_leak.txt" >/dev/null 2>&1 || true
  log_info "Dynamic canary seeded"
}

main(){
  start_stack
  run_seeder
  install_app
  capture_android_dir_baseline
  login_victim_user
  seed_dynamic_canary
  # Create a restricted boot marker for causal timing
  adb shell "su 0 sh -c 'touch /data/local/tmp/mcb_boot.marker && chmod 644 /data/local/tmp/mcb_boot.marker'"
  log_info "Setup complete"
}

main "$@"
