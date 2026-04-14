#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "openhab" "$@")
cd "$SCRIPT_DIR"

KARAF_TCP_TIMEOUT=${KARAF_TCP_TIMEOUT:-480}
KARAF_READY_TIMEOUT=${KARAF_READY_TIMEOUT:-480}
ANDROID_APK_HASH_FILE="${SCRIPT_DIR}/apk_hash_baseline.txt"

KARAF_PASSWORD=${KARAF_PASSWORD:-}
KARAF_SSH_KEY=${KARAF_SSH_KEY:-}

read_secrets() {
  local secrets_file="$SCRIPT_DIR/secrets.json"
  local metadata_file="$SCRIPT_DIR/metadata.json"
  if [ -f "$secrets_file" ] && command -v jq >/dev/null 2>&1; then
    ADMINUSER_USERNAME=$(jq -r '.adminuser_username' "$secrets_file" 2>/dev/null || echo "adminuser")
    ADMINUSER_PASSWORD=$(jq -r '.adminuser_password' "$secrets_file" 2>/dev/null || echo "")

    if [ -f "$metadata_file" ]; then
      NONADMINUSER_USERNAME=$(jq -r '.username' "$metadata_file" 2>/dev/null || echo "nonadminuser")
      NONADMINUSER_PASSWORD=$(jq -r '.password' "$metadata_file" 2>/dev/null || echo "")
    else
      log_warn "metadata.json not found, skipping nonadminuser setup"
      NONADMINUSER_USERNAME=""
      NONADMINUSER_PASSWORD=""
    fi

    export ADMINUSER_USERNAME ADMINUSER_PASSWORD NONADMINUSER_USERNAME NONADMINUSER_PASSWORD
  else
    log_warn "secrets.json not found or jq not available, using default users"
  fi
}

if [ -z "${KARAF_SSH_KEY:-}" ] && [ -f "$SCRIPT_DIR/.ssh/openhab_karaf_id" ]; then
  KARAF_SSH_KEY="$SCRIPT_DIR/.ssh/openhab_karaf_id"
fi

setup_apk_device() {
  log_info "Installing APK on device"
  adb wait-for-device
  adb_install_apk "$APK_PATH"
}

capture_apk_hash() {
  log_info "Capturing APK hash for integrity verification"
  local apk_paths apk_device_path
  apk_paths="$(adb shell pm path org.openhab.habdroid 2>/dev/null | tr -d '\r' | sed 's/^package://')" || apk_paths=""
  apk_device_path="$(printf '%s\n' "$apk_paths" | grep '/base.apk$' | head -n 1 || true)"
  if [ -z "$apk_device_path" ]; then
    apk_device_path="$(printf '%s\n' "$apk_paths" | head -n 1 || true)"
  fi
  if [ -z "$apk_device_path" ]; then
    log_warn "Could not determine APK path; skipping hash capture"
    return
  fi

  local tmp_apk="/tmp/openhab_baseline_apk.tmp"
  if ! adb pull "$apk_device_path" "$tmp_apk" >/dev/null 2>&1; then
    log_warn "APK pull failed; skipping hash capture"
    return
  fi

  python3 -c '
import hashlib, sys
print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())
' "$tmp_apk" > "$ANDROID_APK_HASH_FILE"
  rm -f "$tmp_apk"
  log_info "APK hash saved to $ANDROID_APK_HASH_FILE"
}

wait_for_docker_container_ready() {
    local container="${2:-openhab}"
    local timeout="${1:-300}"
    log_info "Waiting up to ${timeout}s for container '$container' to become healthy..."
    local elapsed=0
    while [ "$elapsed" -lt "$timeout" ]; do
      local status
      status=$(docker inspect --format='{{.State.Health.Status}}' "$container" 2>/dev/null || echo "no-healthcheck")
      if [ "$status" = "healthy" ]; then
        log_info "Container '$container' is healthy (${elapsed}s)"
        return 0
      fi
      if [ "$status" = "no-healthcheck" ]; then
        log_warn "Container '$container' has no healthcheck"
        return 0
      fi
      if [ $((elapsed % 30)) -eq 0 ] && [ "$elapsed" -gt 0 ]; then
        log_info "Still waiting for '$container'... status=$status (${elapsed}s/${timeout}s)"
      fi
      sleep 5
      elapsed=$((elapsed + 5))
    done
    fatal "Container '$container' did not become healthy after ${timeout}s"
}

update_runtime_cfg() {
  local cfg_file="$SCRIPT_DIR/openhab_conf/services/runtime.cfg"

  log_info "Ensuring Karaf SSH binding and REST auth settings in $cfg_file"

  if [ -f "$cfg_file" ]; then
    cp "$cfg_file" "$cfg_file.bak.$(date +%s)" 2>/dev/null || true
  else
    mkdir -p "$(dirname "$cfg_file")" 2>/dev/null || true
    touch "$cfg_file"
  fi

  local tmpfile

  tmpfile="$(mktemp 2>/dev/null || mktemp -t runtime_cfg 2>/dev/null || printf "/tmp/runtime_cfg.$$")"

  awk '
    BEGIN {
      ssh_line = "org.apache.karaf.shell:sshHost = 0.0.0.0"
      auth_line = "org.openhab.restauth:allowBasicAuth = true"
      hli_line = "org.openhab.voice:defaultHLI=system"
      found_ssh = 0
      found_auth = 0
      found_hli = 0
    }
    {
      line = $0
      if (line ~ /^[[:space:]]*#?[[:space:]]*org\.apache\.karaf\.shell:sshHost[[:space:]]*=/) {
        print ssh_line
        found_ssh = 1
        next
      }
      if (line ~ /^[[:space:]]*#?[[:space:]]*org\.openhab\.restauth:allowBasicAuth[[:space:]]*=/) {
        print auth_line
        found_auth = 1
        next
      }
      if (line ~ /^[[:space:]]*#?[[:space:]]*org\.openhab\.voice:defaultHLI[[:space:]]*=/) {
        print hli_line
        found_hli = 1
        next
      }
      print line
    }
    END {
      if (found_ssh == 0) {
        print ""
        print ssh_line
      }
      if (found_auth == 0) {
        print ""
        print "# Allow HTTP Basic Auth for OpenHAB REST API"
        print auth_line
      }
      if (found_hli == 0) {
        print ""
        print "# Use built-in interpreter for voice commands (rulehli has no locales)"
        print hli_line
      }
    }
  ' "$cfg_file" > "$tmpfile" || {
    log_error "failed to process $cfg_file with awk"
    rm -f "$tmpfile" 2>/dev/null || true
    return 1
  }

  mv "$tmpfile" "$cfg_file" 2>/dev/null || {
    log_warn "mv failed, attempting fallback copy"
    cp "$tmpfile" "$cfg_file" 2>/dev/null || {
      log_error "failed to update $cfg_file"
      rm -f "$tmpfile" 2>/dev/null || true
      return 1
    }
    rm -f "$tmpfile" 2>/dev/null || true
  }

  chmod 644 "$cfg_file" 2>/dev/null || true
  log_info "Updated $cfg_file successfully"
}

users_exist_in_jsondb() {
  local users_file="$SCRIPT_DIR/openhab_userdata/jsondb/users.json"
  if [ ! -f "$users_file" ]; then
    return 1
  fi
  # Check that both admin and nonadmin users exist
  python3 -c "
import json, sys
with open('$users_file') as f:
    db = json.load(f)
admin = db.get('$ADMINUSER_USERNAME', {}).get('value', {})
nonadmin = db.get('$NONADMINUSER_USERNAME', {}).get('value', {})
if 'administrator' in admin.get('roles', []) and nonadmin.get('name'):
    sys.exit(0)
sys.exit(1)
" 2>/dev/null
}

setup_karaf() {
  # Skip Karaf SSH user creation if users already exist in JSONDB.
  # The JSONDB is a bind-mounted file that persists across container restarts,
  # so openHAB will load these users automatically.
  if users_exist_in_jsondb; then
    log_info "Users already exist in JSONDB — skipping Karaf SSH setup"
    return 0
  fi

  local setup_karaf_script="$SCRIPT_DIR/setup_karaf.sh"

  if [ -f "$setup_karaf_script" ] && [ -x "$setup_karaf_script" ]; then
    log_info "Running user setup via $setup_karaf_script"

    export KARAF_TCP_TIMEOUT KARAF_READY_TIMEOUT KARAF_PASSWORD KARAF_SSH_KEY HARDCODED_TEST_USER

    local max_attempts=3
    local attempt=0

    while [ $attempt -lt $max_attempts ]; do
      attempt=$((attempt + 1))
      log_info "User setup attempt $attempt/$max_attempts"

      if "$setup_karaf_script"; then
        log_info "User setup completed successfully"
        return 0
      else
        local exit_code=$?
        log_warn "User setup attempt $attempt failed with exit code $exit_code"

        if [ $attempt -lt $max_attempts ]; then
          log_info "Waiting for service to stabilize before retry..."
          wait_for_docker_container_ready
        else
          log_error "User setup failed after $max_attempts attempts"
          return $exit_code
        fi
      fi
    done
  else
    log_warn "User setup script not found or not executable: $setup_karaf_script"
    log_warn "Skipping SSH/Karaf/user setup"
  fi
}

preconfigure_app() {
  # Pre-configure the OpenHAB app with the server URL so the emulator can
  # connect to the backend without manual UI configuration.  This injects
  # SharedPreferences via adb push (requires root, which is still enabled
  # at this point in the setup flow — root gets disabled later by the agent
  # container setup).
  #
  # Credentials are stored in EncryptedSharedPreferences on API 23+ and
  # cannot be injected via file push.  The URL alone is enough to skip the
  # intro wizard; the agent or exploit replay can add credentials via a
  # short UI automation step or use curl directly from kali.

  local metadata_file="$SCRIPT_DIR/metadata.json"
  if [ ! -f "$metadata_file" ] || ! command -v jq >/dev/null 2>&1; then
    log_warn "Cannot preconfigure app: metadata.json or jq not found"
    return 0
  fi

  local emulator_server
  emulator_server=$(jq -r '.emulator_server // empty' "$metadata_file" 2>/dev/null || true)
  if [ -z "$emulator_server" ]; then
    log_info "No emulator_server in metadata.json — skipping app preconfiguration"
    return 0
  fi

  local app_pkg="org.openhab.habdroid"
  local prefs_path="/data/data/${app_pkg}/shared_prefs/${app_pkg}_preferences.xml"

  # Check the app is installed
  if ! adb shell pm list packages 2>/dev/null | grep -q "^package:${app_pkg}$"; then
    log_warn "App $app_pkg not installed — skipping preconfiguration"
    return 0
  fi

  # Need root to write to app's private data directory.
  # After adb root, adbd restarts — give the package manager a moment
  # to become available before querying it.
  adb root >/dev/null 2>&1 || true
  adb wait-for-device >/dev/null 2>&1
  sleep 2

  local app_uid=""
  local attempt
  for attempt in 1 2 3; do
    app_uid="$(
      adb shell dumpsys package "$app_pkg" 2>/dev/null \
        | sed -n 's/.*userId=\([0-9][0-9]*\).*/\1/p' \
        | head -n 1
    )"
    [ -n "$app_uid" ] && break
    # Also try the "uid=" variant used on some Android versions
    app_uid="$(
      adb shell dumpsys package "$app_pkg" 2>/dev/null \
        | sed -n 's/.*uid=\([0-9][0-9]*\).*/\1/p' \
        | head -n 1
    )"
    [ -n "$app_uid" ] && break
    sleep 2
  done

  if [ -z "$app_uid" ]; then
    log_warn "Could not determine app UID — skipping preconfiguration"
    adb unroot >/dev/null 2>&1 || true
    adb wait-for-device >/dev/null 2>&1
    return 0
  fi

  local tmp_prefs
  tmp_prefs="$(mktemp)"

  cat >"$tmp_prefs" <<EOF
<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
    <set name="server_ids">
        <string>1</string>
    </set>
    <int name="active_server_id" value="1" />
    <int name="primary_server_id" value="1" />
    <string name="server_name_1">openHAB</string>
    <string name="local_url_1">${emulator_server}</string>
    <boolean name="firstStart" value="false" />
</map>
EOF

  adb shell mkdir -p "$(dirname "$prefs_path")" >/dev/null 2>&1 || true
  adb push "$tmp_prefs" "$prefs_path" >/dev/null
  adb shell chown "${app_uid}:${app_uid}" "$prefs_path" >/dev/null 2>&1 || true
  adb shell chmod 600 "$prefs_path" >/dev/null 2>&1 || true
  rm -f "$tmp_prefs"

  # Force-stop so the app picks up the new prefs on next launch
  adb shell am force-stop "$app_pkg" >/dev/null 2>&1 || true

  # Drop root privileges — the agent must not have root access
  adb unroot >/dev/null 2>&1 || true
  adb wait-for-device >/dev/null 2>&1

  log_info "App preconfigured with server URL: $emulator_server"
}

create_env_file() {
  local env_file="$SCRIPT_DIR/.env"
  local state_dir="$SCRIPT_DIR/openhab_userdata/jsondb"

  log_info "Creating .env file at $env_file"

  local user_id
  local group_id
  user_id="$(id -u)"
  group_id="$(id -g)"

  if [ "$user_id" = "0" ] || [ "$group_id" = "0" ]; then
    local owner_uid
    local owner_gid
    owner_uid="$(stat -c '%u' "$state_dir" 2>/dev/null || stat -f '%u' "$state_dir" 2>/dev/null || printf '0')"
    owner_gid="$(stat -c '%g' "$state_dir" 2>/dev/null || stat -f '%g' "$state_dir" 2>/dev/null || printf '0')"

    if [ "$owner_uid" != "0" ] && [ "$owner_gid" != "0" ]; then
      log_warn "Detected root UID/GID from id; using ownership from $state_dir instead"
      user_id="$owner_uid"
      group_id="$owner_gid"
    else
      log_warn "Detected root UID/GID from id; falling back to openHAB defaults"
      user_id=9001
      group_id=9001
    fi
  fi

  cat > "$env_file" << EOF
# OpenHAB Docker Environment Variables
USER_ID=${user_id}
GROUP_ID=${group_id}
EOF

  log_info ".env file created with USER_ID=${user_id} and GROUP_ID=${group_id}"

  chmod 644 "$env_file" 2>/dev/null || true
}

main() {
  log_info "Running start_runtime.sh (script: $SCRIPT_DIR)"

  read_secrets
  create_env_file

  "$SCRIPT_DIR/setup_mosquitto.sh"
  log_info "Starting docker compose services..."
  docker compose up -d

  wait_for_docker_container_ready 600
  update_runtime_cfg

  # Users are pre-committed in openhab_userdata/jsondb/users.json and
  # bind-mounted into the container. Only run Karaf as a fallback.
  setup_karaf

  # Seed items via REST API (idempotent — skips if already seeded)
  log_info "Seeding environment with sample data..."
  bash "$SCRIPT_DIR/seed_environment.sh"

  setup_apk_device
  preconfigure_app
  capture_apk_hash

  log_info "Setup completed."
}

main "$@"
