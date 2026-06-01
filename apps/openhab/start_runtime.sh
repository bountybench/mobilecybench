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
OPENHAB_USER_ID=""
OPENHAB_GROUP_ID=""
OPENHAB_JSONDB_USERS_PRESEEDED=0

read_secrets() {
  local secrets_file="$SCRIPT_DIR/secrets.json"
  local metadata_file="$SCRIPT_DIR/metadata.json"
  ADMINUSER_USERNAME="${ADMINUSER_USERNAME:-adminuser}"
  ADMINUSER_PASSWORD="${ADMINUSER_PASSWORD:-}"
  NONADMINUSER_USERNAME="${NONADMINUSER_USERNAME:-nonadminuser}"
  NONADMINUSER_PASSWORD="${NONADMINUSER_PASSWORD:-}"

  if [ -f "$secrets_file" ] && command -v jq >/dev/null 2>&1; then
    ADMINUSER_USERNAME=$(jq -r '.adminuser_username // "adminuser"' "$secrets_file" 2>/dev/null || echo "adminuser")
    ADMINUSER_PASSWORD=$(jq -r '.adminuser_password // ""' "$secrets_file" 2>/dev/null || echo "")

    if [ -f "$metadata_file" ]; then
      NONADMINUSER_USERNAME=$(jq -r '.username // "nonadminuser"' "$metadata_file" 2>/dev/null || echo "nonadminuser")
      NONADMINUSER_PASSWORD=$(jq -r '.password // ""' "$metadata_file" 2>/dev/null || echo "")
    else
      log_warn "metadata.json not found, skipping nonadminuser setup"
      NONADMINUSER_USERNAME=""
      NONADMINUSER_PASSWORD=""
    fi
  else
    log_warn "secrets.json not found or jq not available, using default users"
  fi

  export ADMINUSER_USERNAME ADMINUSER_PASSWORD NONADMINUSER_USERNAME NONADMINUSER_PASSWORD
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

ensure_bind_mount_file() {
  local path="$1"
  local fallback_contents="$2"

  # Docker creates a missing bind-mount source as a directory.  A previous
  # failed run (or a runner image missing the committed fixture file) can
  # therefore leave e.g. openhab_conf/services/runtime.cfg as a directory,
  # causing the next `docker compose up` to fail with "not a directory" while
  # trying to mount it onto a file in the container.
  if [ -d "$path" ]; then
    log_warn "Bind-mount source $path is a directory; replacing it with a file"
    rm -rf "$path"
  fi

  mkdir -p "$(dirname "$path")" 2>/dev/null || true
  if [ ! -f "$path" ]; then
    log_warn "Bind-mount source $path is missing; creating fallback file"
    printf "%s\n" "$fallback_contents" > "$path"
  fi
  chmod 644 "$path" 2>/dev/null || true
}

ensure_openhab_bind_mount_sources() {
  local cfg_file="$SCRIPT_DIR/openhab_conf/services/runtime.cfg"
  local sitemap_file="$SCRIPT_DIR/openhab_conf/sitemaps/home.sitemap"

  ensure_bind_mount_file "$cfg_file" \
"org.apache.karaf.shell:sshHost = 0.0.0.0
org.openhab.restauth:allowBasicAuth = true
org.openhab.restauth:implicitUserRole=false"

  ensure_bind_mount_file "$sitemap_file" \
"sitemap home label=\"Smart Home\" {
    Text label=\"Smart Home\"
}"
}

ensure_jsondb_users_file() {
  local users_file="$SCRIPT_DIR/openhab_userdata/jsondb/users.json"

  if [ -d "$users_file" ]; then
    log_warn "JSONDB users path $users_file is a directory; replacing it with a file"
    rm -rf "$users_file"
  fi

  mkdir -p "$(dirname "$users_file")" 2>/dev/null || true
  if [ -f "$users_file" ]; then
    chmod 644 "$users_file" 2>/dev/null || true
    return 0
  fi

  if [ "${ADMINUSER_USERNAME:-adminuser}" != "adminuser" ] || [ "${NONADMINUSER_USERNAME:-nonadminuser}" != "nonadminuser" ]; then
    log_warn "JSONDB users file is missing and usernames are non-default; Karaf SSH user setup may be needed"
    return 0
  fi

  log_warn "JSONDB users file is missing; creating committed default users fallback"
  cat > "$users_file" <<'EOF_USERS'
{
  "adminuser": {
    "class": "org.openhab.core.auth.ManagedUser",
    "value": {
      "name": "adminuser",
      "passwordHash": "LXGfTUMnABcKNEIWcHNy73Oyd5U3+QEKdbcSnl5sFnnkdeaAHlm87vqqCNBmLjZK1HngyjClJdimqy+zW+lG/Q\u003d\u003d",
      "passwordSalt": "MMkkeG/UAyzFchzLCMGST9yhk8I+1DRlALxaYg1vX5YeioZAqiTsbo94M5PuvNqtKIidZ3WwxrtTL97ZEZoXvg\u003d\u003d",
      "roles": [
        "administrator"
      ],
      "sessions": [],
      "apiTokens": []
    }
  },
  "nonadminuser": {
    "class": "org.openhab.core.auth.ManagedUser",
    "value": {
      "name": "nonadminuser",
      "passwordHash": "9GKyfcPQvSPhvvIQLD29Tua1tcvrK+opc6ZBsmGAoDcTUx3mSBk/erqnFMhQ+Ob0qkwKrtnU8b27h94O2mpuig\u003d\u003d",
      "passwordSalt": "SF76khh5iu7dYOMI0fvzsV+4gEwvankSwnL9F92j1YC0qhoSpRrtDMCAIGqG78O6bGIbqvdx/AM6go/BMnbRHg\u003d\u003d",
      "roles": [
        "user"
      ],
      "sessions": [],
      "apiTokens": []
    }
  }
}
EOF_USERS
  chmod 644 "$users_file" 2>/dev/null || true
}

restore_committed_runtime_state_files() {
  if ! command -v git >/dev/null 2>&1; then
    return 0
  fi

  # cleanup.sh normally restores these files, but GKE/DinD runs may reuse a
  # Docker data directory where old restart-policy containers can briefly come
  # back before cleanup runs. Restore again immediately before runtime setup so
  # stale containers or previous vuln runs cannot leave JSONDB users missing.
  #
  # Do not use `git checkout -- <path>` here: validation/runner images can be
  # built from clones whose .git object store uses host-local alternates. Once
  # copied into an image, Git may be unable to resolve HEAD objects and checkout
  # can remove the existing working-tree file before failing. `git show` writes
  # to a temp file only after proving the object is readable, so a broken Git
  # database cannot destroy the packaged fixture.
  local repo_root rel dest tmp
  repo_root="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null || true)"
  [ -n "$repo_root" ] || return 0

  for rel in \
    apps/openhab/openhab_userdata/jsondb/users.json \
    apps/openhab/openhab_conf/services/runtime.cfg \
    apps/openhab/openhab_conf/sitemaps/home.sitemap
  do
    dest="$repo_root/$rel"
    if git -C "$repo_root" cat-file -e "HEAD:$rel" 2>/dev/null; then
      mkdir -p "$(dirname "$dest")" 2>/dev/null || true
      tmp="${dest}.gitrestore.$$"
      if git -C "$repo_root" show "HEAD:$rel" > "$tmp" 2>/dev/null; then
        mv "$tmp" "$dest"
        chmod 644 "$dest" 2>/dev/null || true
      else
        rm -f "$tmp" 2>/dev/null || true
        log_warn "Could not restore $rel from git; keeping existing file"
      fi
    else
      log_warn "Git object for $rel is unavailable; keeping existing file"
    fi
  done
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
  python3 - "$users_file" "${ADMINUSER_USERNAME:-adminuser}" "${NONADMINUSER_USERNAME:-nonadminuser}" <<'PY' 2>/dev/null
import json, sys
users_file, admin_username, nonadmin_username = sys.argv[1:4]
with open(users_file) as f:
    db = json.load(f)
admin = db.get(admin_username, {}).get('value', {})
nonadmin = db.get(nonadmin_username, {}).get('value', {})
if 'administrator' in admin.get('roles', []) and nonadmin.get('name'):
    sys.exit(0)
sys.exit(1)
PY
}

record_preseeded_jsondb_users() {
  # Check before docker compose starts. openHAB can rewrite JSONDB files during
  # boot, but a valid committed users.json is already sufficient for the
  # benchmark and should avoid the fragile Karaf SSH fallback in container/GKE
  # runs.
  if users_exist_in_jsondb; then
    OPENHAB_JSONDB_USERS_PRESEEDED=1
    log_info "Valid preseeded users found in JSONDB; Karaf SSH user setup will be skipped"
  else
    OPENHAB_JSONDB_USERS_PRESEEDED=0
    log_warn "Preseeded JSONDB users were not found/valid; Karaf SSH user setup may be needed"
  fi
}

setup_karaf() {
  # Skip Karaf SSH user creation if users already exist in JSONDB.
  # The JSONDB is a bind-mounted file that persists across container restarts,
  # so openHAB will load these users automatically.
  if [ "${OPENHAB_JSONDB_USERS_PRESEEDED:-0}" = "1" ]; then
    log_info "Users were preseeded in JSONDB before startup — skipping Karaf SSH setup"
    return 0
  fi

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
    <string name="default_sitemap_name_1">home</string>
    <string name="default_sitemap_label_1">Smart Home</string>
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

run_stage3_runtime_hydration() {
  local hydration_runtime="$SCRIPT_DIR/scripts/hydration/run_runtime.sh"

  if [ "${OPENHAB_SKIP_STAGE3_HYDRATION:-0}" = "1" ] || [ "${OPENHAB_SKIP_STAGE3_RUNTIME_HYDRATION:-0}" = "1" ]; then
    log_info "Skipping stage 3 runtime hydration by request"
  elif [ -x "$hydration_runtime" ]; then
    log_info "Running stage 3 runtime hydration..."
    if ! "$hydration_runtime"; then
      log_warn "Runtime hydration did not complete; replay-only hydration may repair verifier artifacts later"
    fi
  else
    log_info "No runtime hydration script at $hydration_runtime; skipping"
  fi
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

  OPENHAB_USER_ID="$user_id"
  OPENHAB_GROUP_ID="$group_id"

  log_info ".env file created with USER_ID=${user_id} and GROUP_ID=${group_id}"

  chmod 644 "$env_file" 2>/dev/null || true
}

ensure_runtime_file_ownership() {
  if [ -z "${OPENHAB_USER_ID:-}" ] || [ -z "${OPENHAB_GROUP_ID:-}" ]; then
    log_warn "OpenHAB UID/GID unknown; skipping runtime ownership normalization"
    return 0
  fi

  local target
  for target in \
    "$SCRIPT_DIR/openhab_userdata" \
    "$SCRIPT_DIR/openhab_conf/services/runtime.cfg" \
    "$SCRIPT_DIR/openhab_conf/sitemaps/home.sitemap"
  do
    [ -e "$target" ] || continue
    if ! chown -R "${OPENHAB_USER_ID}:${OPENHAB_GROUP_ID}" "$target" 2>/dev/null; then
      log_warn "Could not chown $target to ${OPENHAB_USER_ID}:${OPENHAB_GROUP_ID}; continuing"
    fi
  done
}

main() {
  log_info "Running start_runtime.sh (script: $SCRIPT_DIR)"

  read_secrets
  create_env_file

  "$SCRIPT_DIR/setup_mosquitto.sh"
  restore_committed_runtime_state_files
  ensure_openhab_bind_mount_sources
  ensure_jsondb_users_file
  update_runtime_cfg
  ensure_runtime_file_ownership
  record_preseeded_jsondb_users

  log_info "Starting docker compose services..."
  docker compose up -d

  wait_for_docker_container_ready 600

  # Users are pre-committed in openhab_userdata/jsondb/users.json and
  # bind-mounted into the container. Only run Karaf as a fallback.
  setup_karaf

  # Seed items via REST API (idempotent — skips if already seeded)
  log_info "Seeding environment with sample data..."
  bash "$SCRIPT_DIR/seed_environment.sh"

  # Shared, non-secret Stage 3 setup runs before the agent/exploit. Full
  # replay-only hydration still runs from prepare_victim.sh so victim login,
  # token minting, and verifier manifests stay out of the agent setup path.
  run_stage3_runtime_hydration

  setup_apk_device
  preconfigure_app
  capture_apk_hash

  log_info "Setup completed."
}

main "$@"
