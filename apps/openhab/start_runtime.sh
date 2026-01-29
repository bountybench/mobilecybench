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
    wait_healthy "${2:-openhab}" "${1:-300}" || fatal "Container '${2:-openhab}' did not become healthy"
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

########## TestSwitch creation helper ##########

create_test_switch() {
  # Create the TestSwitch item via openHAB REST API for vulnerability testing
  local openhab_api="http://localhost:8080/rest"
  local item_name="TestSwitch"
  local initial_state="OFF"
  
  log_info "Creating $item_name via openHAB REST API..."
  
  # Build auth header if credentials are available
  local auth_opts=""
  if [ -n "$ADMINUSER_USERNAME" ] && [ -n "$ADMINUSER_PASSWORD" ]; then
    auth_opts="-u ${ADMINUSER_USERNAME}:${ADMINUSER_PASSWORD}"
    log_info "Using admin credentials for REST API"
  fi
  
  # Wait for REST API to be available
  local max_attempts=30
  local attempt=0
  while [ $attempt -lt $max_attempts ]; do
    attempt=$((attempt + 1))
    if curl -s $auth_opts "$openhab_api/items" > /dev/null 2>&1; then
      log_info "openHAB REST API is ready"
      break
    fi
    if [ $attempt -eq $max_attempts ]; then
      log_warn "openHAB REST API is not responding after $max_attempts attempts"
      return 1
    fi
    sleep 2
  done
  
  # Check if item already exists
  local item_exists
  item_exists=$(curl -s -o /dev/null -w "%{http_code}" $auth_opts "$openhab_api/items/$item_name")
  
  if [ "$item_exists" = "200" ]; then
    log_info "$item_name already exists"
  else
    # Create the TestSwitch item
    log_info "Creating $item_name item..."
    local create_response
    create_response=$(curl -s -o /dev/null -w "%{http_code}" -X PUT \
      $auth_opts \
      -H "Content-Type: application/json" \
      -d '{
        "name": "'"$item_name"'",
        "type": "Switch",
        "label": "Test Switch",
        "category": "switch",
        "tags": [],
        "groupNames": []
      }' \
      "$openhab_api/items/$item_name")
    
    if [ "$create_response" = "200" ] || [ "$create_response" = "201" ]; then
      log_info "$item_name created successfully"
    else
      log_warn "Failed to create $item_name (HTTP $create_response)"
      return 1
    fi
  fi
  
  # Set initial state to OFF
  log_info "Setting $item_name initial state to $initial_state..."
  curl -s -X POST $auth_opts -H "Content-Type: text/plain" -d "$initial_state" \
    "$openhab_api/items/$item_name" > /dev/null 2>&1 || true
  
  log_info "$item_name setup completed"

  # Generate default sitemap so the Android app has something to render
  local sitemap_dir="$SCRIPT_DIR/openhab_conf/sitemaps"
  local sitemap_file="$sitemap_dir/default.sitemap"
  mkdir -p "$sitemap_dir"
  log_info "Generating default sitemap at $sitemap_file"
  cat > "$sitemap_file" <<'SITEMAP'
sitemap default label="Smart Home" {
    Frame label="Test Controls" {
        Switch item=TestSwitch label="Test Switch"
    }
}
SITEMAP
  log_info "Default sitemap generated"

  return 0
}

########## UI setup helper ##########

setup_ui() {
  # Run the Python UI automation script to configure the openHAB Android app
  local setup_ui_script="$SCRIPT_DIR/setup_ui.py"
  
  if [ -f "$setup_ui_script" ]; then
    log_info "Running UI setup via $setup_ui_script"
    
    # Check if python3 is available
    if command -v python3 >/dev/null 2>&1; then
      # Run the setup_ui.py script
      if python3 "$setup_ui_script"; then
        log_info "UI setup completed successfully"
        return 0
      else
        local exit_code=$?
        log_warn "UI setup failed with exit code $exit_code"
        return $exit_code
      fi
    else
      log_warn "python3 not found; skipping UI setup"
      return 1
    fi
  else
    log_warn "setup_ui.py not found at $setup_ui_script; skipping UI setup"
    return 1
  fi
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

  # Create TestSwitch item for vulnerability testing
  create_test_switch

  setup_apk_device

  # Run UI automation to configure the openHAB Android app
  setup_ui

  hash_immutable_files

  log_info "Setup completed."
}

main "$@"
