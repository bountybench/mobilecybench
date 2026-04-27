#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "ntfy-android" "$@")
cd "$SCRIPT_DIR"

HEALTH_TIMEOUT=${HEALTH_TIMEOUT:-180}

TARGET_PACKAGE="io.heckel.ntfy"
TARGET_DIR="/data/data/${TARGET_PACKAGE}"
ANDROID_BASELINE_FILE="${SCRIPT_DIR}/baseline_android_dir.txt"
ANDROID_APK_HASH_FILE="${SCRIPT_DIR}/apk_hash_baseline.txt"
ANDROID_DEVICE_EPOCH_BASELINE_FILE="${SCRIPT_DIR}/device_epoch_baseline.txt"
CRASH_SNIFFER_LOG="${SCRIPT_DIR}/crash_sniffer.log"
CRASH_SNIFFER_PID_FILE="${SCRIPT_DIR}/crash_sniffer.pid"
EMULATOR_GATEWAY="http://10.0.2.2:8080"

generate_secrets_if_missing() {
  # secrets.json is gitignored and runtime-generated. cleanup.sh deletes it
  # between experiments so each experiment gets fresh random values. Within
  # one experiment, multiple start_runtime.sh calls (Phase 1, Phase 2) reuse
  # the same file so credentials match what the seeded ntfy server expects.
  local secrets="$SCRIPT_DIR/secrets.json"
  if [[ -f "$secrets" ]] && jq -e '.alice_secret' "$secrets" >/dev/null 2>&1; then
    return 0
  fi
  log_info "Generating secrets.json with per-experiment random values"
  python3 - "$secrets" <<'PY'
import json, secrets, sys
path = sys.argv[1]
def short(): return secrets.token_hex(4)   # 8 hex chars
def topic(): return secrets.token_hex(16)  # 32 hex chars
data = {
  "alice_secret":   f"alice_{short()}",
  "bob_secret":     f"bob_{short()}",
  "charlie_secret": f"charlie_{short()}",
  "topic_private_alice":   topic(),
  "topic_private_bob":     topic(),
  "topic_private_charlie": topic(),
}
with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, sort_keys=True)
PY
}

load_secrets() {
  local secrets="$SCRIPT_DIR/secrets.json"
  generate_secrets_if_missing
  export ALICE_PASSWORD=$(jq -r '.alice_secret' "$secrets")
  export BOB_PASSWORD=$(jq -r '.bob_secret' "$secrets")
  export CHARLIE_PASSWORD=$(jq -r '.charlie_secret' "$secrets")
  export TOPIC_ALICE=$(jq -r '.topic_private_alice' "$secrets")
  export TOPIC_BOB=$(jq -r '.topic_private_bob' "$secrets")
  export TOPIC_CHARLIE=$(jq -r '.topic_private_charlie' "$secrets")
}

start_stack() {
  log_info "Starting ntfy-server"
  load_secrets
  docker compose up -d --remove-orphans
}

wait_for_health() {
  wait_healthy ntfy-server "$HEALTH_TIMEOUT" || fatal "ntfy-server did not become healthy"
}

sync_device_time_to_host() {
  log_info "Syncing device clock to host time..."
  local host_epoch_ms
  host_epoch_ms=$(($(date +%s) * 1000))
  if adb shell cmd alarm set-time "$host_epoch_ms" >/dev/null 2>&1; then
    log_info "Device clock set via cmd alarm (epoch_ms=$host_epoch_ms)"
  else
    log_warn "Failed to sync device clock via cmd alarm set-time (continuing)"
  fi
}

install_app() {
  log_info "Installing ntfy-android"
  adb uninstall "$TARGET_PACKAGE" >/dev/null 2>&1 || true
  adb_install_apk "$APK_PATH"
  adb shell pm grant "$TARGET_PACKAGE" android.permission.POST_NOTIFICATIONS >/dev/null 2>&1 || log_warn "POST_NOTIFICATIONS grant skipped"
}

configure_app_defaults() {
  log_info "Pointing app to local Docker server..."

  adb shell "am force-stop $TARGET_PACKAGE" >/dev/null 2>&1

  local pref_file_name="MainPreferences.xml"
  cat <<EOF > "$pref_file_name"
<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
    <string name="DefaultBaseURL">$EMULATOR_GATEWAY</string>
    <string name="ConnectionProtocol">jsonhttp</string>
</map>
EOF

  if ! adb push "$pref_file_name" /data/local/tmp/ >/dev/null 2>&1; then
    rm "$pref_file_name"
    fatal "Failed to push preferences file"
  fi

  if ! adb shell su 0 <<EOF >/dev/null 2>&1
    mkdir -p /data/data/$TARGET_PACKAGE/shared_prefs
    mv /data/local/tmp/$pref_file_name /data/data/$TARGET_PACKAGE/shared_prefs/

    # Standard Android permissions
    chmod 660 /data/data/$TARGET_PACKAGE/shared_prefs/$pref_file_name
    APP_UID=\$(stat -c %u /data/data/$TARGET_PACKAGE)
    chown \$APP_UID:\$APP_UID /data/data/$TARGET_PACKAGE/shared_prefs/$pref_file_name

    # Force the OS to acknowledge the file change (suppress verbose output)
    restorecon /data/data/$TARGET_PACKAGE/shared_prefs/$pref_file_name 2>/dev/null || true
EOF
  then
    rm "$pref_file_name"
    fatal "Failed to configure app preferences"
  fi

  rm "$pref_file_name"

  adb shell sync >/dev/null 2>&1
  log_info "App preferences updated. DefaultBaseURL set to $EMULATOR_GATEWAY"
}

launch_app() {
  log_info "Launching ntfy..."
  adb shell am start -n "$TARGET_PACKAGE/.ui.MainActivity" >/dev/null 2>&1 || log_warn "Failed to launch app"
  sleep 2
}

capture_apk_hash() {
  log_info "Capturing APK hash for integrity verification"
  local apk_paths apk_device_path device_hash
  apk_paths="$(adb shell pm path "$TARGET_PACKAGE" 2>/dev/null | tr -d '\r' | sed 's/^package://')" || apk_paths=""
  apk_device_path="$(printf '%s\n' "$apk_paths" | grep '/base.apk$' | head -n 1 || true)"
  if [ -z "$apk_device_path" ]; then
    apk_device_path="$(printf '%s\n' "$apk_paths" | head -n 1 || true)"
  fi
  if [ -z "$apk_device_path" ]; then
    log_warn "Could not determine APK path; skipping hash capture"
    return
  fi

  # Prefer hashing on-device to avoid flaky host-side APK pulls.
  device_hash="$(
    adb shell su 0 sh -c "toybox sha256sum '$apk_device_path' 2>/dev/null || sha256sum '$apk_device_path' 2>/dev/null" 2>/dev/null \
      | tr -d '\r' \
      | awk '{print $1}' \
      | head -n 1 \
      | xargs || true
  )"
  if [[ "$device_hash" =~ ^[0-9a-fA-F]{64}$ ]]; then
    echo "$device_hash" | tr '[:upper:]' '[:lower:]' > "$ANDROID_APK_HASH_FILE"
    log_info "APK hash saved to $ANDROID_APK_HASH_FILE"
    return
  fi

  # Fallback: pull + hash on host with retries.
  local tmp_apk="/tmp/ntfy_baseline_apk.tmp"
  rm -f "$tmp_apk"
  for _i in $(seq 1 5); do
    if adb pull "$apk_device_path" "$tmp_apk" >/dev/null 2>&1; then
      [[ -s "$tmp_apk" ]] && break
    fi
    rm -f "$tmp_apk"
    sleep 1
  done
  if [ ! -s "$tmp_apk" ]; then
    log_warn "APK pull failed; skipping hash capture"
    return
  fi

  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$tmp_apk" | awk '{print $1}' > "$ANDROID_APK_HASH_FILE"
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$tmp_apk" | awk '{print $1}' > "$ANDROID_APK_HASH_FILE"
  else
    python3 -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "$tmp_apk" > "$ANDROID_APK_HASH_FILE"
  fi

  rm -f "$tmp_apk"
  log_info "APK hash saved to $ANDROID_APK_HASH_FILE"
}

capture_device_epoch_baseline() {
  log_info "Capturing device epoch baseline -> $ANDROID_DEVICE_EPOCH_BASELINE_FILE"
  local device_epoch=""
  for _i in $(seq 1 15); do
    device_epoch="$(adb shell date +%s 2>/dev/null | tr -d '\r' | head -n 1 | xargs || true)"
    [[ "$device_epoch" =~ ^[0-9]+$ ]] && break
    sleep 1
  done
  [[ "$device_epoch" =~ ^[0-9]+$ ]] || fatal "Failed to capture device epoch baseline (got: '$device_epoch')"
  echo "$device_epoch" > "$ANDROID_DEVICE_EPOCH_BASELINE_FILE"
  log_info "Device epoch baseline saved ($device_epoch)"
}

stop_crash_sniffer() {
  if [ -f "$CRASH_SNIFFER_PID_FILE" ]; then
    local old_pid
    old_pid=$(cat "$CRASH_SNIFFER_PID_FILE" 2>/dev/null || true)
    if [ -n "$old_pid" ] && kill -0 "$old_pid" 2>/dev/null; then
      kill "$old_pid" 2>/dev/null || true
      wait "$old_pid" 2>/dev/null || true
    fi
    rm -f "$CRASH_SNIFFER_PID_FILE"
  fi
}

clear_crash_logcat() {
  log_info "Clearing logcat crash buffer baseline..."
  adb logcat -c -b crash >/dev/null 2>&1 || true
}

start_crash_sniffer() {
  stop_crash_sniffer
  rm -f "$CRASH_SNIFFER_LOG"
  log_info "Starting crash logcat sniffer -> $CRASH_SNIFFER_LOG"
  # Host-side crash sniffer for verifier (threadtime+uid+printable).
  adb logcat -b crash -v threadtime,uid,printable >> "$CRASH_SNIFFER_LOG" 2>/dev/null &
  echo $! > "$CRASH_SNIFFER_PID_FILE"
  log_info "Crash sniffer started (PID=$(cat "$CRASH_SNIFFER_PID_FILE"))"
}

capture_baseline() {
  # Capture file list repeatedly until it stabilizes (two consecutive
  # snapshots match). This avoids races with async SharedPreferences
  # writes that may still be in flight after seeding, without needing
  # to force-stop the app.
  #
  # Pre-step: deterministically wait for shared_prefs/SubscriberService.xml
  # to appear. SubscriberService.startService() writes this file via
  # saveServiceState() once the foreground service has been launched
  # by WorkManager's ServiceStartWorker, which runs asynchronously
  # several seconds after MainActivity launches. If we snapshot before
  # that write lands, the file shows up later (e.g. after pm clear +
  # prepare_victim) and the synthetic-vuln verifier misclassifies it
  # as a path-traversal write outside cache/attachments/. Waiting for
  # the file here closes that race so the baseline is consistent
  # across the start_runtime → exploit → prepare_victim → verify flow.
  local sub_prefs="$TARGET_DIR/shared_prefs/SubscriberService.xml"
  log_info "Waiting for SubscriberService.xml to be written..."
  local sub_seen=0
  for _i in $(seq 1 30); do
    if adb shell su 0 test -f "$sub_prefs" 2>/dev/null; then
      sub_seen=1
      break
    fi
    sleep 1
  done
  if [ "$sub_seen" = 1 ]; then
    log_info "SubscriberService.xml present, proceeding with baseline capture"
  else
    log_warn "SubscriberService.xml not seen within 30s — baseline may be racy"
  fi

  log_info "Capturing Android baseline -> $ANDROID_BASELINE_FILE"
  local prev="" curr=""
  for _i in $(seq 1 10); do
    curr="$(adb shell "su 0 sh -c 'cd \"$TARGET_DIR\" && find . -type f'" 2>/dev/null | tr -d '\r' | sort)"
    if [ "$curr" = "$prev" ]; then
      echo "$curr" > "$ANDROID_BASELINE_FILE"
      log_info "Baseline stabilized ($(echo "$curr" | wc -l | xargs) entries)"
      return 0
    fi
    prev="$curr"
    sleep 2
  done
  # Use last snapshot even if not fully stable
  log_warn "Baseline did not fully stabilize after 10 attempts; using last snapshot"
  echo "$curr" > "$ANDROID_BASELINE_FILE"
}

run_ntfy_seeding() {
  log_info "Running ntfy seeding"
  python3 ntfy_seeding.py || log_warn "ntfy_seeding.py failed"
}

main() {
  start_stack
  wait_for_health
  install_app
  sync_device_time_to_host
  capture_apk_hash
  capture_device_epoch_baseline
  clear_crash_logcat
  start_crash_sniffer
  configure_app_defaults
  launch_app
  run_ntfy_seeding
  capture_baseline
  log_info "Setup complete for ntfy"
}

main "$@"
