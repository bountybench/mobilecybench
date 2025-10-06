#!/usr/bin/env bash
set -euo pipefail

APP_NAME=${APP_NAME:-}

KARAF_TCP_TIMEOUT=${KARAF_TCP_TIMEOUT:-120}
KARAF_READY_TIMEOUT=${KARAF_READY_TIMEOUT:-120}

# KARAF options
KARAF_PASSWORD=${KARAF_PASSWORD:-}
KARAF_SSH_KEY=${KARAF_SSH_KEY:-}

# Function to read secrets from JSON file
read_secrets() {
  local secrets_file="$SCRIPT_DIR/secrets.json"
  if [ -f "$secrets_file" ] && command -v jq >/dev/null 2>&1; then
    # Extract user credentials from secrets.json
    ADMINUSER_PASSWORD=$(jq -r '.adminuser_password' "$secrets_file" 2>/dev/null || echo "")
    NONADMINUSER_PASSWORD=$(jq -r '.nonadminuser_password' "$secrets_file" 2>/dev/null || echo "")
    
    # Set users (will be handled by setup_user.sh)
    export ADMINUSER_PASSWORD NONADMINUSER_PASSWORD
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
  
  LOG "Found APK: $apk, Using adb: $adb_bin, Target device: $serial"
  
  # Wait for device and boot completion (for emulators)
  "$adb_bin" -s "$serial" wait-for-device
  [[ "$serial" == emulator-* ]] && wait_for_boot_completed "$adb_bin" "$serial" 180
  
  install_apk_on_device "$adb_bin" "$serial" "$apk"
}

########## Docker readiness helper ##########

wait_for_docker_service_ready() {
  # Wait for OpenHAB docker container to be ready by checking container health and port availability
  local timeout=${1:-120}
  local start_time=$(date +%s)
  local container_name="openhab"
  
  LOG "Waiting for OpenHAB docker service to be ready..."
  
  # First, wait for container to be running
  while ! docker ps --filter "name=$container_name" --filter "status=running" | grep -q "$container_name" 2>/dev/null; do
    local current_time=$(date +%s)
    if [ $((current_time - start_time)) -ge $timeout ]; then
      LOG "Container $container_name not running after ${timeout}s, proceeding anyway"
      return 0
    fi
    read -t 1 -N 1 < /dev/null 2>/dev/null || true
  done
  
  # Then wait for the web interface port to be available
  LOG "Waiting for OpenHAB web interface (port 8080) to be ready..."
  while ! (echo > /dev/tcp/127.0.0.1/8080) >/dev/null 2>&1; do
    local current_time=$(date +%s)
    if [ $((current_time - start_time)) -ge $timeout ]; then
      LOG "OpenHAB web interface (8080) not ready after ${timeout}s, proceeding anyway"
      return 0
    fi
    read -t 0.5 -N 1 < /dev/null 2>/dev/null || true
  done
  
  # Finally, wait for the Karaf SSH port to be available (needed for user creation)
  LOG "Waiting for Karaf SSH service (port 8101) to be ready..."
  while ! (echo > /dev/tcp/127.0.0.1/8101) >/dev/null 2>&1; do
    local current_time=$(date +%s)
    if [ $((current_time - start_time)) -ge $timeout ]; then
      LOG "Karaf SSH service (8101) not ready after ${timeout}s, proceeding anyway"
      return 0
    fi
    read -t 0.5 -N 1 < /dev/null 2>/dev/null || true
  done
  
  # Verify Karaf service is fully initialized by attempting a simple command
  LOG "Karaf SSH port available, testing service readiness..."
  local karaf_ready_timeout=30
  local karaf_ready_start=$(date +%s)
  
  while ! echo "info" | timeout 5 ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o BatchMode=yes -p 8101 karaf@127.0.0.1 2>/dev/null | grep -q "Karaf" 2>/dev/null; do
    local current_time=$(date +%s)
    if [ $((current_time - karaf_ready_start)) -ge $karaf_ready_timeout ]; then
      LOG "Karaf service readiness test timed out after ${karaf_ready_timeout}s, proceeding anyway"
      break
    fi
    read -t 1 -N 1 < /dev/null 2>/dev/null || true
  done
  
  LOG "OpenHAB docker service is ready"
}

########## Karaf SSH configuration helper ##########

configure_karaf_ssh_binding() {
  # Configure Karaf SSH to bind to 0.0.0.0 so it can be accessed from anywhere
  local runtime_cfg="$SCRIPT_DIR/openhab_conf/services/runtime.cfg"
  
  if [ -f "$runtime_cfg" ]; then
    LOG "Configuring Karaf SSH to bind to 0.0.0.0 for external access"
    LOG "WARNING: This allows SSH access from any network interface. Ensure you have proper authentication configured!"
    
    # Check if the line is already uncommented and set to 0.0.0.0
    if grep -q "^org\.apache\.karaf\.shell:sshHost = 0\.0\.0\.0" "$runtime_cfg"; then
      LOG "Karaf SSH already configured to bind to 0.0.0.0"
      return 0
    fi
    
    # Create backup of the original file
    cp "$runtime_cfg" "$runtime_cfg.bak.$(date +%s)" 2>/dev/null || true
    
    # Uncomment and set the sshHost parameter to 0.0.0.0
    if sed -i.tmp 's/^#org\.apache\.karaf\.shell:sshHost = 0\.0\.0\.0/org.apache.karaf.shell:sshHost = 0.0.0.0/' "$runtime_cfg" 2>/dev/null; then
      rm -f "$runtime_cfg.tmp" 2>/dev/null || true
      LOG "Successfully configured Karaf SSH to bind to 0.0.0.0"
    else
      # If sed with -i.tmp failed, try without the extension
      sed -i 's/^#org\.apache\.karaf\.shell:sshHost = 0\.0\.0\.0/org.apache.karaf.shell:sshHost = 0.0.0.0/' "$runtime_cfg" 2>/dev/null || {
        LOG "WARNING: Failed to automatically configure Karaf SSH binding"
        LOG "Please manually uncomment the line '#org.apache.karaf.shell:sshHost = 0.0.0.0' in $runtime_cfg"
        return 1
      }
      LOG "Successfully configured Karaf SSH to bind to 0.0.0.0"
    fi
    
    # Verify the change was applied
    if grep -q "^org\.apache\.karaf\.shell:sshHost = 0\.0\.0\.0" "$runtime_cfg"; then
      LOG "Verification: Karaf SSH binding configuration applied successfully"
    else
      LOG "WARNING: Karaf SSH binding configuration may not have been applied correctly"
    fi
  else
    LOG "WARNING: Runtime configuration file not found: $runtime_cfg"
    LOG "Karaf SSH binding will use default settings (localhost only)"
  fi
}

########## User setup helper ##########

setup_users() {
  # Call the separate setup_user.sh script to handle SSH/Karaf/user setup
  local setup_user_script="$SCRIPT_DIR/setup_user.sh"
  
  if [ -f "$setup_user_script" ] && [ -x "$setup_user_script" ]; then
    LOG "Running user setup via $setup_user_script"
    
    # Export environment variables so they're available to the child script
    export KARAF_TCP_TIMEOUT KARAF_READY_TIMEOUT KARAF_PASSWORD KARAF_SSH_KEY HARDCODED_TEST_USER
    
    # Run the user setup script with retry logic
    local max_attempts=3
    local attempt=0
    
    while [ $attempt -lt $max_attempts ]; do
      attempt=$((attempt + 1))
      LOG "User setup attempt $attempt/$max_attempts"
      
      if "$setup_user_script"; then
        LOG "User setup completed successfully"
        return 0
      else
        local exit_code=$?
        LOG "User setup attempt $attempt failed with exit code $exit_code"
        
        if [ $attempt -lt $max_attempts ]; then
          LOG "Waiting for service to stabilize before retry..."
          # Wait for container and service to be ready again
          wait_for_docker_service_ready 60
        else
          LOG "User setup failed after $max_attempts attempts"
          return $exit_code
        fi
      fi
    done
  else
    LOG "User setup script not found or not executable: $setup_user_script"
    LOG "Skipping SSH/Karaf/user setup"
  fi
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

<<<<<<< HEAD
# Optional: Cloudflare tunnel token
# If this is set to a valid token, the cloudflared service will be started
# Leave empty or unset to disable the cloudflared service
=======
# Optional: Cloudflare tunnel token (leave empty if not using)
>>>>>>> 09a6d2b27 (For rebase)
CLOUDFLARE_TUNNEL_TOKEN=
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

<<<<<<< HEAD
  # Define env_file path for use throughout main function
  local env_file="$SCRIPT_DIR/.env"

  # Create .env file for docker-compose
  create_env_file

  # Create Mosquitto configuration
  "$SCRIPT_DIR/setup_mosquitto.sh"
=======
  # Create .env file for docker-compose
  create_env_file

>>>>>>> 09a6d2b27 (For rebase)
  # Start openhab via docker-compose
  if [ -f "$SCRIPT_DIR/docker-compose.yml" ]; then
    if command -v docker >/dev/null 2>&1; then
      LOG "Starting docker compose services..."
<<<<<<< HEAD
      
      # Check if CLOUDFLARE_TUNNEL_TOKEN is set and not empty
      local compose_profiles=""
      if [ -f "$env_file" ]; then
        # Source the .env file to get CLOUDFLARE_TUNNEL_TOKEN
        source "$env_file"
      fi
      
      if [ -n "${CLOUDFLARE_TUNNEL_TOKEN:-}" ] && [ "$CLOUDFLARE_TUNNEL_TOKEN" != "" ]; then
        LOG "Cloudflare tunnel token found, enabling cloudflared service"
        compose_profiles="--profile cloudflare"
      else
        LOG "No Cloudflare tunnel token found, skipping cloudflared service"
      fi
      
      if command -v docker-compose >/dev/null 2>&1; then
        docker-compose -f "$SCRIPT_DIR/docker-compose.yml" $compose_profiles up -d
      else
        docker compose -f "$SCRIPT_DIR/docker-compose.yml" $compose_profiles up -d
=======
      if command -v docker-compose >/dev/null 2>&1; then
        docker-compose -f "$SCRIPT_DIR/docker-compose.yml" up -d
      else
        docker compose -f "$SCRIPT_DIR/docker-compose.yml" up -d
>>>>>>> 09a6d2b27 (For rebase)
      fi
      # Wait for OpenHAB service to be ready before proceeding (increased timeout for Karaf)
      wait_for_docker_service_ready 180
    else
      LOG "docker not found; skipping docker start"
    fi
  fi

  # Configure Karaf SSH to bind to 0.0.0.0 for external access
  configure_karaf_ssh_binding

  # Setup SSH key for Karaf authentication and create test users
  setup_users

  # Setup APK on device
  setup_apk_device
  
  LOG "Setup completed."
}

main "$@"
