#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
source "$SCRIPT_DIR/helpers/victim_state.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "jerboa" "$@")
cd "$SCRIPT_DIR"

SEED_SCRIPT="${SCRIPT_DIR}/jerboa_setup.py"
DEFAULT_OUTPUT="baseline_manifest.json"
SEED_OUTPUT=${SEED_OUTPUT:-$DEFAULT_OUTPUT}

TARGET_PACKAGE="com.jerboa"
TARGET_DIR="/data/data/${TARGET_PACKAGE}"
ANDROID_BASELINE_FILE="${SCRIPT_DIR}/baseline_android_dir.txt"
PROBE_AUTH_DEVICE_PATH="/data/local/tmp/.mcb_jerboa_probe_auth.json"
BASELINE_FP_DEVICE_PATH="/data/local/tmp/.mcb_jerboa_baseline_fingerprint"

start_stack(){
  [[ -f "$SCRIPT_DIR/docker-compose.yml" ]] || fatal "docker-compose.yml not found at $SCRIPT_DIR/docker-compose.yml"
  log_info "Starting docker stack"
  # Ensure reruns start from a clean Lemmy data state. The seeded corpus is the
  # benchmark baseline, so stale named volumes from a previous attempt must be
  # removed instead of being reused.
  docker compose down --remove-orphans -v >/dev/null 2>&1 || true
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

inject_emulator_ca(){
  local ca_script="$ROOT_DIR/utils/inject_system_ca.sh"
  if [[ ! -x "$ca_script" ]]; then
    fatal "CA injection script not found: $ca_script"
  fi

  log_info "Injecting repo CA into emulator trust store"
  "$ca_script" || fatal "Failed to inject emulator CA"
  wait_for_device_boot 120 || fatal "Device not ready after CA injection"
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

seed_probe_auth_cache_once(){
  log_info "Caching probe auth and baseline fingerprint on device..."

  local auth_tmp auth_host fp_tmp fp_host fingerprint
  auth_tmp="$(mktemp)"
  fp_tmp="$(mktemp)"

  REQUESTS_CA_BUNDLE="$SCRIPT_DIR/../../tls/rootCA.pem" \
  SCRIPT_DIR="$SCRIPT_DIR" PYTHONPATH="$SCRIPT_DIR/../.." AUTH_TMP="$auth_tmp" \
    python3 - <<'PY'
import json
import os
from pathlib import Path

from jerboa_setup import LemmySeeder

script_dir = Path(os.environ["SCRIPT_DIR"])
secrets = json.loads((script_dir / "secrets.json").read_text())
seeder = LemmySeeder(os.getenv("LEMMY_URL", "https://localhost:8536"), secrets)
admin_jwt = seeder.login_user("admin", secrets.get("admin_password", ""))
alice_jwt = seeder.login_user("alice", secrets.get("alice_password", ""))
if not admin_jwt or not alice_jwt:
    raise RuntimeError("unable to obtain probe auth JWTs")
Path(os.environ["AUTH_TMP"]).write_text(
    json.dumps(
        {
            "admin_jwt": admin_jwt,
            "alice_jwt": alice_jwt,
        },
        sort_keys=True,
    ),
    encoding="utf-8",
)
PY
  local auth_status=$?
  if [ "$auth_status" -ne 0 ] || [ ! -s "$auth_tmp" ]; then
    rm -f "$auth_tmp" "$fp_tmp"
    return 1
  fi

  auth_host="$auth_tmp"
  if command -v cygpath >/dev/null 2>&1; then
    auth_host="$(cygpath -w "$auth_tmp")"
  fi
  MSYS_NO_PATHCONV=1 adb push "$auth_host" /data/local/tmp/mcb_jerboa_probe_auth.json >/dev/null || {
    rm -f "$auth_tmp" "$fp_tmp"
    return 1
  }
  adb shell "su 0 sh -c 'mv /data/local/tmp/mcb_jerboa_probe_auth.json \"$PROBE_AUTH_DEVICE_PATH\" && chmod 600 \"$PROBE_AUTH_DEVICE_PATH\"'" >/dev/null || {
    rm -f "$auth_tmp" "$fp_tmp"
    return 1
  }

  fingerprint="$(
    REQUESTS_CA_BUNDLE="$SCRIPT_DIR/../../tls/rootCA.pem" \
    PYTHONPATH="$SCRIPT_DIR/../.." \
      python3 "$SCRIPT_DIR/jerboa_state_fingerprint.py" fingerprint
  )" || {
    rm -f "$auth_tmp" "$fp_tmp"
    return 1
  }
  [ -n "$fingerprint" ] || {
    rm -f "$auth_tmp" "$fp_tmp"
    return 1
  }
  printf '%s\n' "$fingerprint" > "$fp_tmp"

  fp_host="$fp_tmp"
  if command -v cygpath >/dev/null 2>&1; then
    fp_host="$(cygpath -w "$fp_tmp")"
  fi
  MSYS_NO_PATHCONV=1 adb push "$fp_host" /data/local/tmp/mcb_jerboa_baseline_fingerprint >/dev/null || {
    rm -f "$auth_tmp" "$fp_tmp"
    return 1
  }
  adb shell "su 0 sh -c 'mv /data/local/tmp/mcb_jerboa_baseline_fingerprint \"$BASELINE_FP_DEVICE_PATH\" && chmod 600 \"$BASELINE_FP_DEVICE_PATH\"'" >/dev/null || {
    rm -f "$auth_tmp" "$fp_tmp"
    return 1
  }

  rm -f "$auth_tmp" "$fp_tmp"
  log_info "Probe auth cache and baseline fingerprint stored"
}

seed_probe_auth_cache(){
  jerboa_retry 3 5 seed_probe_auth_cache_once || fatal "Probe auth cache seeding failed after retries"
}

main(){
  start_stack
  run_seeder
  inject_emulator_ca
  install_app
  jerboa_restore_benchmark_baseline
  log_info "Benchmark-user scaffolding and shared baseline artifacts seeded"
  seed_probe_auth_cache
  # Snapshot only after the replay floor and benchmark scaffolding exist;
  # earlier capture misses legitimate baseline state and is misleading.
  capture_android_dir_baseline
  # Create a restricted boot marker for causal timing
  adb shell "su 0 sh -c 'touch /data/local/tmp/mcb_boot.marker && chmod 644 /data/local/tmp/mcb_boot.marker'"
  log_info "Setup complete"
}

main "$@"
