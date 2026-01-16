#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
ANDROID_HOME="${HOME}/.android-sdk"
source "$ROOT_DIR/utils/android.sh"

APP_NAME=${APP_NAME:-}

KARAF_TCP_TIMEOUT=${KARAF_TCP_TIMEOUT:-120}
KARAF_READY_TIMEOUT=${KARAF_READY_TIMEOUT:-120}

# KARAF options
KARAF_PASSWORD=${KARAF_PASSWORD:-}
KARAF_SSH_KEY=${KARAF_SSH_KEY:-}

# Function to read secrets from JSON file
read_secrets() {
  local secrets_file="$SCRIPT_DIR/secrets.json"
  local metadata_file="$SCRIPT_DIR/metadata.json"
  if [ -f "$secrets_file" ] && command -v jq >/dev/null 2>&1; then
    # Extract admin user credentials from secrets.json
    ADMINUSER_USERNAME=$(jq -r '.adminuser_username' "$secrets_file" 2>/dev/null || echo "adminuser")
    ADMINUSER_PASSWORD=$(jq -r '.adminuser_password' "$secrets_file" 2>/dev/null || echo "")

    # Extract nonadminuser credentials from metadata.json (not secrets)
    if [ -f "$metadata_file" ]; then
      NONADMINUSER_USERNAME=$(jq -r '.username' "$metadata_file" 2>/dev/null || echo "nonadminuser")
      NONADMINUSER_PASSWORD=$(jq -r '.password' "$metadata_file" 2>/dev/null || echo "")
    else
      LOG "Warning: metadata.json not found, skipping nonadminuser setup"
      NONADMINUSER_USERNAME=""
      NONADMINUSER_PASSWORD=""
    fi

    # Set users (will be handled by setup_karaf.sh)
    export ADMINUSER_USERNAME ADMINUSER_PASSWORD NONADMINUSER_USERNAME NONADMINUSER_PASSWORD
  else
    LOG "Warning: secrets.json not found or jq not available, using default users"
  fi
}

# helpers
LOG()  { printf "%s\n" "$*" >&2; }
ERR()  { printf "ERROR: %s\n" "$*" >&2; exit 1; }

# CLI parsing (simple)
while [ $# -gt 0 ]; do
  case "$1" in
    --app=*) APP_NAME="${1#--app=}"; shift ;;
    --help|-h) printf "Usage: %s [--app=name]\n" "$0"; exit 0 ;;
    *) ERR "Unknown argument: $1" ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

# If there's a repo-local karaf private key prefer that (non-invasive)
if [ -z "${KARAF_SSH_KEY:-}" ] && [ -f "$SCRIPT_DIR/.ssh/openhab_karaf_id" ]; then
  KARAF_SSH_KEY="$SCRIPT_DIR/.ssh/openhab_karaf_id"
fi

########## Core functions ##########

find_apk() {
  # Check local APK first, then APP_NAME location, then search
  local candidates=(
    "$SCRIPT_DIR/apk/openhab.apk"
    "${APP_NAME:+$ROOT_DIR/apps/$APP_NAME/apk/$APP_NAME.apk}"
  )
  
  for apk in "${candidates[@]}"; do
    [ -n "$apk" ] && [ -f "$apk" ] && { printf "%s" "$apk"; return 0; }
  done
  
  # Search pattern as fallback
  find "$ROOT_DIR/apps" -name "*.apk" -path "*/apk/*" | head -1
}

find_adb() {
  command -v adb || printf "%s" "${ANDROID_SDK_ROOT:-${ANDROID_HOME}}/platform-tools/adb"
}

choose_device() {
  local adb_bin="$1"
  # Use ANDROID_SERIAL if set
  [ -n "${ANDROID_SERIAL:-}" ] && { printf "%s" "$ANDROID_SERIAL"; return 0; }
  
  # Get first available device, prefer emulator
  local devices=($("$adb_bin" devices | awk 'NR>1 && $2=="device" {print $1}'))
  [ ${#devices[@]} -eq 0 ] && ERR "No adb devices found"
  
  # Return emulator if available, otherwise first device
  for d in "${devices[@]}"; do
    [[ "$d" == emulator-* ]] && { printf "%s" "$d"; return 0; }
  done
  printf "%s" "${devices[0]}"
}

wait_for_boot_completed() {
  local adb_bin="$1" serial="$2" timeout=${3:-120} start_ts=$(date +%s)
  local check_interval=1 last_check=0
  
  while ! "$adb_bin" -s "$serial" shell getprop sys.boot_completed 2>/dev/null | grep -q '^1'; do
    local current_time=$(date +%s)
    [ $((current_time - start_ts)) -ge $timeout ] && ERR "Boot timeout (>${timeout}s)"
    "$adb_bin" -s "$serial" wait-for-device 2>/dev/null || true
    
    # Use adaptive polling - check more frequently initially, then back off
    if [ $((current_time - last_check)) -ge $check_interval ]; then
      last_check=$current_time
      # Increase interval up to 5 seconds to reduce polling frequency
      [ $check_interval -lt 5 ] && check_interval=$((check_interval + 1))
    fi
  done
  LOG "Device $serial boot completed"
}

install_apk_on_device() {
  local adb_bin="$1" serial="$2" apk="$3"
  LOG "Installing APK $apk -> device $serial"
  
  # Try install with -r, then with -r -g if that fails
  if ! "$adb_bin" -s "$serial" install -r "$apk" 2>/dev/null; then
    LOG "Retrying with -g flag"
    "$adb_bin" -s "$serial" install -r -g "$apk" || ERR "APK install failed"
  fi
  LOG "APK install completed"
}

setup_apk_device() {
  # Find and install APK on device
  local apk=$(find_apk) || { LOG "No APK found; skipping device setup"; return 0; }
  local adb_bin=$(find_adb) || ERR "adb not found"
  local serial=$(choose_device "$adb_bin")
  local device=$(choose_device "$adb_bin")

  
  LOG "Found APK: $apk, Using adb: $adb_bin, Target device: $serial"
  
  # Wait for device and boot completion (for emulators)
  "$adb_bin" -s "$serial" wait-for-device
  [[ "$serial" == emulator-* ]] && wait_for_boot_completed "$adb_bin" "$serial" 180
  
  install_apk_on_device "$adb_bin" "$serial" "$apk"

}

########## Readiness helpers ########## 

# Wait for Docker container to be running and report healthy 
wait_for_docker_container_ready() {
    local timeout=${1:-300}       # seconds
    local container_name="${2:-openhab}"
    local start_time=$(date +%s)

    LOG "Waiting for Docker container '$container_name' to be running (timeout: ${timeout}s)..."

    # Wait for container to exist and be running
    while ! docker ps --filter "name=$container_name" --filter "status=running" --format '{{.Names}}' \
        | grep -qx "$container_name" 2>/dev/null; do

        local now=$(date +%s)
        if [ $((now - start_time)) -ge $timeout ]; then
            ERR "Container '$container_name' did not start within ${timeout}s"
        fi

        # Passive 1s delay
        read -t 1 -N 1 < /dev/null 2>/dev/null || true
    done

    LOG "Container '$container_name' is running, monitoring health status..."

    # Poll Docker health status until it reports "healthy" or times out
    local check_count=0
    while :; do
        local status
        status=$(docker inspect --format '{{.State.Health.Status}}' "$container_name" 2>/dev/null || echo "unknown")
        check_count=$((check_count + 1))

        if [ "$status" = "healthy" ]; then
            LOG "Container '$container_name' is healthy ✅"
            break
        elif [[ "$status" = "unhealthy" || "$status" = "starting" ]]; then
            # Log every 5 checks so output isn't spammy
            if (( check_count % 5 == 0 )); then
                LOG "$(date '+%H:%M:%S') | Health check $check_count: still waiting (status=$status)"
            fi
        else
            LOG "$(date '+%H:%M:%S') | Health check $check_count: unknown status '$status'"
        fi

        local now=$(date +%s)
        if [ $((now - start_time)) -ge $timeout ]; then
            ERR "Timed out waiting for container '$container_name' to become healthy after ${timeout}s"
        fi

        # Passive 1s delay
        read -t 1 -N 1 < /dev/null 2>/dev/null || true
    done

    LOG "Docker container '$container_name' is ready."
}

########## Runtime configuration helpers ##########
update_runtime_cfg() {
  local cfg_file="$SCRIPT_DIR/openhab_conf/services/runtime.cfg"

  LOG "Ensuring Karaf SSH binding and REST auth settings in $cfg_file"

  if [ -f "$cfg_file" ]; then
    cp "$cfg_file" "$cfg_file.bak.$(date +%s)" 2>/dev/null || true
  else
    mkdir -p "$(dirname "$cfg_file")" 2>/dev/null || true
    touch "$cfg_file"
  fi

  local tmpfile

  # Create a temp file safely on Linux or macOS
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
    LOG "ERROR: failed to process $cfg_file with awk"
    rm -f "$tmpfile" 2>/dev/null || true
    return 1
  }

  mv "$tmpfile" "$cfg_file" 2>/dev/null || {
    LOG "WARNING: mv failed, attempting fallback copy"
    cp "$tmpfile" "$cfg_file" 2>/dev/null || {
      LOG "ERROR: failed to update $cfg_file"
      rm -f "$tmpfile" 2>/dev/null || true
      return 1
    }
    rm -f "$tmpfile" 2>/dev/null || true
  }

  chmod 644 "$cfg_file" 2>/dev/null || true
  LOG "Updated $cfg_file successfully"
}

########## User setup helper ##########

setup_karaf() {
  # Call the separate setup_karaf.sh script to handle SSH/Karaf/user setup
  local setup_karaf_script="$SCRIPT_DIR/setup_karaf.sh"

  if [ -f "$setup_karaf_script" ] && [ -x "$setup_karaf_script" ]; then
    LOG "Running user setup via $setup_karaf_script"

    # Export environment variables so they're available to the child script
    export KARAF_TCP_TIMEOUT KARAF_READY_TIMEOUT KARAF_PASSWORD KARAF_SSH_KEY HARDCODED_TEST_USER
    
    # Run the user setup script with retry logic
    local max_attempts=3
    local attempt=0
    
    while [ $attempt -lt $max_attempts ]; do
      attempt=$((attempt + 1))
      LOG "User setup attempt $attempt/$max_attempts"
      
      if "$setup_karaf_script"; then
        LOG "User setup completed successfully"
        return 0
      else
        local exit_code=$?
        LOG "User setup attempt $attempt failed with exit code $exit_code"
        
        if [ $attempt -lt $max_attempts ]; then
          LOG "Waiting for service to stabilize before retry..."
          # Wait for container and service to be ready again
          wait_for_docker_container_ready
        else
          LOG "User setup failed after $max_attempts attempts"
          return $exit_code
        fi
      fi
    done
  else
    LOG "User setup script not found or not executable: $setup_karaf_script"
    LOG "Skipping SSH/Karaf/user setup"
  fi
}

########## Direcory hash helpers ##########
compute_dir_hash() {
  local path="$1"
  # Find all files, compute sha256sum, sort, and hash the list
  find "$path" -type f -exec sha256sum {} + | awk '{print $1}' | sort | sha256sum | awk '{print $1}'
}

wait_for_filesystem_stable() {
  local dir="$1"
  local max_wait=${2:-30}  # seconds
  local check_interval=2
  local stable_duration=5  # seconds of no changes needed
  
  LOG "Waiting for filesystem activity to stabilize in $dir..."
  
  local last_hash=""
  local stable_since=0
  local start_time=$(date +%s)
  
  while true; do
    local current_hash=$(compute_dir_hash "$dir")
    local now=$(date +%s)
    
    if [ "$current_hash" = "$last_hash" ]; then
      # Hash unchanged, increase stable counter
      stable_since=$((stable_since + check_interval))
      
      if [ $stable_since -ge $stable_duration ]; then
        LOG "Filesystem stable for ${stable_duration}s in $dir"
        return 0
      fi
    else
      # Hash changed, reset counter
      stable_since=0
      last_hash="$current_hash"
    fi
    
    # Timeout check
    if [ $((now - start_time)) -ge $max_wait ]; then
      LOG "WARNING: Filesystem did not stabilize within ${max_wait}s"
      return 1
    fi
    
    sleep $check_interval
  done
}

hash_immutable_files() {
  local baseline="$SCRIPT_DIR/baseline.json"
  LOG "Waiting for files to stabilize before hashing..."

  # Wait for files to be stable
  wait_for_filesystem_stable "$SCRIPT_DIR/openhab_userdata/"

  LOG "Hashing immutable directories and saving to $baseline"
  
  cat > "$baseline" << EOF
{
 "openhab_userdata/jsondb/users.json": "$(compute_dir_hash "$SCRIPT_DIR/openhab_userdata/jsondb/users.json")"
}
EOF
}

########## Environment file creation helper ##########

create_env_file() {
  local env_file="$SCRIPT_DIR/.env"
  
  LOG "Creating .env file at $env_file"
  
  # Get current user ID and group ID for proper permissions
  local user_id=$(id -u)
  local group_id=$(id -g)
  
  # Use fallback values if id command fails
  user_id=${user_id:-9001}
  group_id=${group_id:-9001}
  
  # Create .env file with proper environment variables
  cat > "$env_file" << EOF
# OpenHAB Docker Environment Variables
USER_ID=${user_id}
GROUP_ID=${group_id}
EOF

  LOG ".env file created with USER_ID=${user_id} and GROUP_ID=${group_id}"
  
  # Set appropriate permissions on the .env file
  chmod 644 "$env_file" 2>/dev/null || true
}

########## Main ##########

main() {
  LOG "Running setup.sh (script: $SCRIPT_DIR, root: $ROOT_DIR)"

  # Read secrets from JSON file
  read_secrets

  # Define env_file path for use throughout main function
  local env_file="$SCRIPT_DIR/.env"

  # Create .env file for docker-compose
  create_env_file

  # Create Mosquitto configuration
  "$SCRIPT_DIR/setup_mosquitto.sh"
  # Start openhab via docker-compose
  if [ -f "$SCRIPT_DIR/docker-compose.yml" ]; then
    if command -v docker >/dev/null 2>&1; then
      LOG "Starting docker compose services..."
      
      # Check if CLOUDFLARE_TUNNEL_TOKEN is set and not empty
      local compose_profiles=""
      if [ -f "$env_file" ]; then
        # Source the .env file to get CLOUDFLARE_TUNNEL_TOKEN
        source "$env_file"
      fi
      
      if command -v docker-compose >/dev/null 2>&1; then
        docker-compose -f "$SCRIPT_DIR/docker-compose.yml" $compose_profiles up -d
      else
        docker compose -f "$SCRIPT_DIR/docker-compose.yml" $compose_profiles up -d
      fi
      # Wait for OpenHAB service to be ready before proceeding
      wait_for_docker_container_ready
    else
      LOG "docker not found; skipping docker start"
    fi
  fi

  # Update runtime.cfg to ensure proper SSH binding and REST auth settings
  update_runtime_cfg

  # Setup SSH key for Karaf authentication and create test users
  setup_karaf

  # Install APK on connected device if available
  setup_apk_device

  # Hash immutable files and save baseline
  hash_immutable_files
  
  LOG "Setup completed."
}

main "$@"