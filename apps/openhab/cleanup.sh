#!/usr/bin/env bash
set -euo pipefail

# cleanup.sh
#
# Safely remove generated files and stop/remove docker containers started
# from this repository. Will NOT remove any .apk files.
#

LOG() { printf "%s\n" "$*" >&2; }
ERR() { printf "ERROR: %s\n" "$*" >&2; exit 1; }


KARAF_SSH_KEY=${KARAF_SSH_KEY:-}
KARAF_PASSWORD=${KARAF_PASSWORD:-}

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Function to read secrets from JSON file
read_secrets() {
  local secrets_file="$ROOT_DIR/secrets.json"
  if [ -f "$secrets_file" ] && command -v jq >/dev/null 2>&1; then
    # Extract user credentials from secrets.json
    ADMINUSER_PASSWORD=$(jq -r '.adminuser_password' "$secrets_file" 2>/dev/null || echo "")
    NONADMINUSER_PASSWORD=$(jq -r '.nonadminuser_password' "$secrets_file" 2>/dev/null || echo "")
  else
    LOG "Warning: secrets.json not found or jq not available"
  fi
}

# Read secrets
read_secrets

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"

: "${KARAF_SSH_KEY:=$ROOT_DIR/.ssh/openhab_karaf_id}"
: "${KARAF_SSH_KEY:=$ROOT_DIR/.ssh/openhab_karaf_id}"

run_cmd() {
  eval "$@"
}

# Wait for Karaf to become available on port 8101
wait_for_karaf() {
  local max_attempts=24  # 24 attempts * 1 second = 24 seconds total
  local attempt=1
  
  LOG "Waiting for Karaf to become available on port 8101..."
  
  while [ $attempt -le $max_attempts ]; do
    if nc -vz 127.0.0.1 8101 >/dev/null 2>&1; then
      LOG "Karaf is now available (attempt $attempt/$max_attempts)"
      return 0
    fi
    
    if [ $attempt -eq $max_attempts ]; then
      LOG "Timeout waiting for Karaf after ${max_attempts} seconds"
      return 1
    fi
    
    # Use a shorter, more responsive interval
    sleep 1
    attempt=$((attempt + 1))
  done
  
  return 1
}

# Execute a karaf/openhab command over SSH and return output (or non-zero on failure).
karaf_exec_local() {
  cmd="$*"
  LOG "karaf_exec_local: preparing to run karaf command: $cmd"

  # Try password authentication first (simpler for test environments)
  if [ -n "${KARAF_PASSWORD:-}" ]; then
    if command -v sshpass >/dev/null 2>&1; then
      LOG "karaf_exec_local: using sshpass (password auth)"
      sshpass -p "$KARAF_PASSWORD" ssh -o ConnectTimeout=10 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p 8101 karaf@127.0.0.1 "$cmd"
      return $?
    else
      LOG "karaf_exec_local: KARAF_PASSWORD set but sshpass not available"
    fi
  fi

  # Fall back to SSH key authentication
  ssh_opts=(-o ConnectTimeout=10 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p 8101 -o BatchMode=yes)
  [ -n "${KARAF_SSH_KEY:-}" ] && ssh_opts=( -i "$KARAF_SSH_KEY" "${ssh_opts[@]}")
  LOG "karaf_exec_local: falling back to SSH key auth with opts: ${ssh_opts[*]}"
  
  if ssh "${ssh_opts[@]}" karaf@127.0.0.1 "$cmd"; then
    return $?
  fi

  LOG "karaf_exec_local: Unable to run karaf command. Configure SSH key auth or set KARAF_PASSWORD and install sshpass. Skipping: $cmd"
  return 2
}

# Attempt to remove test users from OpenHAB via karaf.
remove_test_users() {
  # Remove users based on available credentials or use the hardcoded test user as fallback
  local users_removed=0
  
  # Check if karaf is reachable first; run a harmless command
  if ! karaf_exec_local "openhab:users list" >/tmp/karaf_users_out 2>&1; then
    LOG "Karaf not reachable or command failed; cannot remove users. See /tmp/karaf_users_out for details if available."
    return 2
  fi
  
  # Remove adminuser  
  if [ -n "${ADMINUSER_PASSWORD:-}" ]; then
    remove_user "adminuser"
    users_removed=$((users_removed + 1))
  fi
  
  # Remove nonadminuser
  if [ -n "${NONADMINUSER_PASSWORD:-}" ]; then
    remove_user "nonadminuser"
    users_removed=$((users_removed + 1))
  fi
  
  # Log if no users were removed
  if [ $users_removed -eq 0 ]; then
    LOG "No user credentials found in secrets.json - no users to remove"
  fi
}

remove_user() {
  local username="$1"
  
  LOG "Attempting to remove user: $username"

  if ! grep -Fq "$username" /tmp/karaf_users_out; then
    LOG "User '$username' not present according to karaf; nothing to remove."
    return 0
  fi

  # Run remove command. The command to remove is 'openhab:users remove <username>'
  if karaf_exec_local "openhab:users remove $username;" >/tmp/karaf_users_remove_out_$username 2>&1; then
    LOG "Removed user '$username'"
    return 0
  else
    if grep -qi "not found" /tmp/karaf_users_remove_out_$username 2>/dev/null; then
      LOG "User '$username' was not found by karaf during removal; continuing"
      return 0
    fi
    LOG "Failed to remove user '$username'. Inspect /tmp/karaf_users_remove_out_$username for details."
    return 1
  fi
}

# Docker cleanup
docker_cleanup() {
  compose_file="$ROOT_DIR/docker-compose.yml"
  if [ ! -f "$compose_file" ]; then
    LOG "No docker-compose.yml in repo root; skipping docker cleanup."
    return 0
  fi

  if ! command -v docker >/dev/null 2>&1; then
    LOG "Docker not available; skipping docker cleanup."
    return 0
  fi

  # Select compose invoker: prefer docker-compose (legacy) if present
  if command -v docker-compose >/dev/null 2>&1; then
    invoker=(docker-compose -f "$compose_file")
  else
    invoker=(docker compose -f "$compose_file")
  fi

  down_args=(down --volumes --remove-orphans)

  LOG "Bringing down docker-compose services defined in $compose_file"
  run_cmd "${invoker[*]} ${down_args[*]}"
  LOG "Docker cleanup requested. Check 'docker ps' to verify." 
}

# Filesystem cleanup
files_cleanup() {
  candidates=(
    "$ROOT_DIR/build"
    "$ROOT_DIR/mobile/build"
    "$ROOT_DIR/mobile/.gradle"
    "$ROOT_DIR/.gradle"
    "$ROOT_DIR/lint/tmp"
  )

  # Add any apps/*/build directories but do not remove apps/*/apk
  while IFS= read -r -d '' d; do
    candidates+=("$d")
  done < <(find "$ROOT_DIR/apps" -maxdepth 2 -type d -name build -print0 2>/dev/null || true)

  # Remove each candidate if it exists and does not contain any .apk files.
  for p in "${candidates[@]}"; do
    [ -e "$p" ] || continue

    # If path contains any .apk file, skip it to preserve APKs
    if find "$p" -type f -name "*.apk" -print -quit | grep -q .; then
      LOG "Skipping removal of '$p' because it contains .apk files (preserving APKs)."
      continue
    fi

    LOG "Removing: $p"
    rm -rf "$p"
  done

  # Remove OpenHAB configuration directories completely
  openhab_dirs=(
    "$ROOT_DIR/openhab_conf"
    "$ROOT_DIR/openhab_addons"
    "$ROOT_DIR/openhab_userdata"
  )
  
  for d in "${openhab_dirs[@]}"; do
    if [ -d "$d" ]; then
      LOG "Removing OpenHAB directory: $d"
      rm -rf "$d"
    fi
  done
}

# If Karaf is not reachable locally, try to start the compose stack so we can 
# perform user removal. This is best-effort.
compose_file="$ROOT_DIR/docker-compose.yml"
if [ -f "$compose_file" ] && command -v docker >/dev/null 2>&1; then
  # Only attempt to start if karaf (8101) is not reachable
  if ! nc -vz 127.0.0.1 8101 >/dev/null 2>&1; then
    LOG "Karaf not reachable; attempting to start docker-compose to allow user removal"
    if command -v docker-compose >/dev/null 2>&1; then
      invoker=(docker-compose -f "$compose_file")
    else
      invoker=(docker compose -f "$compose_file")
    fi
    run_cmd "${invoker[*]} up -d"
    # Wait for karaf to come up (best-effort)
    wait_for_karaf
  fi
fi

# Attempt to remove any test user created by setup.sh (best-effort; won't abort on failures)
if ! remove_test_users; then
  LOG "Test user removal returned non-zero; continuing with remaining cleanup results." || true
fi

# Now that users have been handled (or attempted), bring down docker services
docker_cleanup

# Clean up files after user operations are complete
files_cleanup

LOG "Cleanup complete."
