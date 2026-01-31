#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "openhab" "$@")
cd "$SCRIPT_DIR"

KARAF_TCP_TIMEOUT=${KARAF_TCP_TIMEOUT:-120}
KARAF_READY_TIMEOUT=${KARAF_READY_TIMEOUT:-120}

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

wait_for_docker_container_ready() {
    local timeout=${1:-300}
    local container_name="${2:-openhab}"
    local start_time=$(date +%s)

    log_info "Waiting for container '$container_name' to be healthy (timeout: ${timeout}s)..."
    while true; do
        local status=$(docker inspect --format '{{.State.Health.Status}}' "$container_name" 2>/dev/null || echo "unknown")
        [[ "$status" = "healthy" ]] && { log_info "Container '$container_name' is healthy"; return 0; }
        local now=$(date +%s)
        [[ $((now - start_time)) -ge $timeout ]] && fatal "Timed out waiting for '$container_name' (status: $status)"
        sleep 2
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
      found_ssh = 0
      found_auth = 0
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

setup_karaf() {
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

compute_dir_hash() {
  local path="$1"
  find "$path" -type f -exec sha256sum {} + | awk '{print $1}' | sort | sha256sum | awk '{print $1}'
}

wait_for_filesystem_stable() {
  local dir="$1"
  local max_wait=${2:-30}
  local check_interval=2
  local stable_duration=5

  log_info "Waiting for filesystem activity to stabilize in $dir..."

  local last_hash=""
  local stable_since=0
  local start_time=$(date +%s)

  while true; do
    local current_hash=$(compute_dir_hash "$dir")
    local now=$(date +%s)

    if [ "$current_hash" = "$last_hash" ]; then
      stable_since=$((stable_since + check_interval))

      if [ $stable_since -ge $stable_duration ]; then
        log_info "Filesystem stable for ${stable_duration}s in $dir"
        return 0
      fi
    else
      stable_since=0
      last_hash="$current_hash"
    fi

    if [ $((now - start_time)) -ge $max_wait ]; then
      log_warn "Filesystem did not stabilize within ${max_wait}s"
      return 1
    fi

    sleep $check_interval
  done
}

hash_immutable_files() {
  local baseline="$SCRIPT_DIR/baseline.json"
  log_info "Waiting for files to stabilize before hashing..."

  wait_for_filesystem_stable "$SCRIPT_DIR/openhab_userdata/"

  log_info "Hashing immutable directories and saving to $baseline"

  cat > "$baseline" << EOF
{
 "openhab_userdata/jsondb/users.json": "$(compute_dir_hash "$SCRIPT_DIR/openhab_userdata/jsondb/users.json")"
}
EOF
}

create_env_file() {
  local env_file="$SCRIPT_DIR/.env"

  log_info "Creating .env file at $env_file"

  local user_id=$(id -u)
  local group_id=$(id -g)

  user_id=${user_id:-9001}
  group_id=${group_id:-9001}

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
  wait_for_docker_container_ready

  update_runtime_cfg

  setup_karaf

  setup_apk_device

  hash_immutable_files

  log_info "Setup completed."
}

main "$@"
