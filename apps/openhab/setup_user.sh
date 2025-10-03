#!/usr/bin/env bash
set -euo pipefail

KARAF_TCP_TIMEOUT=${KARAF_TCP_TIMEOUT:-120}
KARAF_READY_TIMEOUT=${KARAF_READY_TIMEOUT:-120}

# KARAF options
KARAF_PASSWORD=${KARAF_PASSWORD:-}
KARAF_SSH_KEY=${KARAF_SSH_KEY:-}
HARDCODED_TEST_USER=${HARDCODED_TEST_USER:-"testuser:testpassword:user"}

# helpers
LOG()  { printf "%s\n" "$*" >&2; }
ERR()  { printf "ERROR: %s\n" "$*" >&2; exit 1; }

# CLI parsing (simple)
while [ $# -gt 0 ]; do
  case "$1" in
    --help|-h) printf "Usage: %s\n" "$0"; exit 0 ;;
    *) ERR "Unknown argument: $1" ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# If there's a repo-local karaf private key prefer that (non-invasive)
if [ -z "${KARAF_SSH_KEY:-}" ] && [ -f "$SCRIPT_DIR/.ssh/openhab_karaf_id" ]; then
  KARAF_SSH_KEY="$SCRIPT_DIR/.ssh/openhab_karaf_id"
fi

########## SSH/Karaf/User Setup Functions ##########

setup_karaf_ssh_key() {
  # Generate and configure SSH key for Karaf authentication
  # This replaces the functionality from add_karaf_pubkey.sh
  local username="${1:-karaf}"
  local roles="${2:-_g_:admingroup}"
  local target="$SCRIPT_DIR/openhab_userdata/etc/keys.properties"
  
  LOG "Setting up Karaf SSH key authentication"
  
  # Ensure we have ssh-keygen available
  if ! command -v ssh-keygen >/dev/null 2>&1; then
    LOG "ssh-keygen not found; skipping SSH key setup"
    return 0
  fi

  # Create .ssh directory and key paths
  mkdir -p "$SCRIPT_DIR/.ssh"
  local key_path="$SCRIPT_DIR/.ssh/openhab_karaf_id"
  local pub_path="$key_path.pub"

  # Generate keypair if it doesn't exist
  if [ -f "$key_path" ] && [ -f "$pub_path" ]; then
    LOG "Reusing existing SSH keypair at $key_path"
  else
    LOG "Generating new SSH keypair at $key_path (no passphrase)"
    if ssh-keygen -t rsa -b 4096 -N "" -C "openhab-karaf-auto" -f "$key_path" >/dev/null 2>&1; then
      chmod 600 "$key_path" || true
      LOG "SSH keypair generated successfully"
    else
      LOG "ssh-keygen failed; skipping SSH key setup"
      return 1
    fi
  fi

  # Set KARAF_SSH_KEY for later use
  KARAF_SSH_KEY="$key_path"
  
  # Configure keys.properties if the target file exists and is writable
  if [ -f "$target" ] && [ -w "$target" ]; then
    # Read the public key and extract the base64 blob
    if [ -f "$pub_path" ]; then
      local keytype keyblob
      read -r keytype keyblob _ < "$pub_path" || {
        LOG "Failed to parse public key: $pub_path"
        return 1
      }
      
      if [ -n "$keyblob" ]; then
        local entry="$username=$keyblob,$roles"
        
        # Check if key is already present
        if grep -Fq "$keyblob" "$target" 2>/dev/null; then
          LOG "SSH key already present in $target"
        else
          # Backup and append the key
          cp "$target" "$target.bak.$(date +%s)" 2>/dev/null || true
          printf "%s\n" "$entry" >> "$target"
          LOG "Added SSH public key for user '$username' to $target"
        fi
      else
        LOG "Failed to extract key blob from $pub_path"
        return 1
      fi
    fi
  else
    LOG "Target file $target not found or not writable; SSH key generated but not configured in Karaf"
    LOG "Set KARAF_SSH_KEY=$key_path to use the generated private key"
  fi
  
  return 0
}

karaf_exec() {
  # Usage: karaf_exec "<karaf-command>"
  # This function connects to Karaf via SSH on localhost (127.0.0.1)
  # For external connections, use: ssh -p 8101 karaf@<docker-host-ip>
  cmd="$*"
  LOG "karaf_exec: preparing to run karaf command: $cmd"
  
  # Try password authentication first (simpler for test environments)
  if [ -n "${KARAF_PASSWORD:-}" ]; then
    if command -v sshpass >/dev/null 2>&1; then
      LOG "karaf_exec: using sshpass (password auth)"
      sshpass -p "$KARAF_PASSWORD" ssh -o ConnectTimeout=10 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p 8101 karaf@127.0.0.1 "$cmd"
      return $?
    else
      LOG "karaf_exec: KARAF_PASSWORD set but sshpass not available"
    fi
  fi

  # Fall back to SSH key authentication
  ssh_opts=(-o ConnectTimeout=10 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p 8101 -o BatchMode=yes)
  [ -n "${KARAF_SSH_KEY:-}" ] && ssh_opts=( -i "$KARAF_SSH_KEY" "${ssh_opts[@]}")
  LOG "karaf_exec: falling back to SSH key auth with opts: ${ssh_opts[*]}"
  ssh "${ssh_opts[@]}" karaf@127.0.0.1 "$cmd"
  return $?
}

create_test_users() {
  # minimal: expect HARDCODED_TEST_USER=username:password:group
  e="$HARDCODED_TEST_USER"
  IFS=':' read -r username password group <<< "$e"
  [ -n "$username" ] || { LOG "No test user configured; skipping"; return 0; }
  LOG "Attempting to create test user '$username' (group=${group:-user}) via karaf"
  LOG "create_test_users: KARAF_SSH_KEY=${KARAF_SSH_KEY:-<none>} KARAF_PASSWORD=${KARAF_PASSWORD:+<set>}"
  # wait for karaf port to be available (simple loop with timeout)
  start=$(date +%s); timeout=${KARAF_TCP_TIMEOUT}
  tcp_check_count=0
  LOG "create_test_users: waiting for karaf SSH port (8101)..."
  while ! (echo > /dev/tcp/127.0.0.1/8101) >/dev/null 2>&1; do
    tcp_check_count=$((tcp_check_count + 1))
    if [ $(( $(date +%s) - start )) -ge $timeout ]; then
      ERR "Timed out waiting for karaf SSH (8101) (>${timeout}s)"
    fi
    # Only log every 10th check to reduce spam
    if [ $((tcp_check_count % 10)) -eq 1 ]; then
      LOG "create_test_users: still waiting for karaf SSH port (attempt $tcp_check_count)..."
    fi
    # Use shorter delay with exponential backoff up to 2s
    local delay=$(( tcp_check_count > 20 ? 2 : (tcp_check_count + 4) / 5 ))
    read -t "$delay" -N 1 < /dev/null 2>/dev/null || true
  done
  LOG "create_test_users: karaf SSH port is available after $tcp_check_count attempts"

  # Wait until Karaf actually accepts commands over SSH. It's common for the
  # TCP port to be open while the SSH service (or the OpenHAB Karaf shell) is
  # still initializing. Attempt a harmless karaf command in a loop until it
  # returns successfully or we hit a timeout.
  start_ready=$(date +%s); ready_timeout=${KARAF_READY_TIMEOUT}
  check_count=0
  LOG "create_test_users: waiting for karaf to become responsive..."
  while true; do
    check_count=$((check_count + 1))
    # Only log every 5th check to reduce spam
    if [ $((check_count % 5)) -eq 1 ]; then
      LOG "create_test_users: checking karaf responsiveness (attempt $check_count)..."
    fi
    
    if karaf_exec "openhab:users list" >/tmp/karaf_users_list_out 2>&1; then
      LOG "create_test_users: karaf is responsive after $check_count attempts"
      break
    fi
    
    # If there are transient connection errors or auth problems, keep retrying
    # for a while as the service finishes starting up.
    if [ $(( $(date +%s) - start_ready )) -ge $ready_timeout ]; then
      LOG "create_test_users: karaf not responsive after $check_count attempts; output saved to /tmp/karaf_users_list_out"
      ERR "Timed out waiting for karaf to become responsive (>${ready_timeout}s). See /tmp/karaf_users_list_out"
    fi
    # Use adaptive delay: start with 0.5s, increase to 3s after 10 attempts
    local delay="0.5"
    if [ $check_count -gt 10 ]; then
      delay="3.0"
    elif [ $check_count -gt 5 ]; then
      delay="1.5"
    fi
    read -t "$delay" -N 1 < /dev/null 2>/dev/null || true
  done

  # Directly attempt to add the user (best-effort) with retries and
  # detection for common transient SSH errors. We no longer query the
  # existing user list before adding.
  max_attempts=5
  attempt=0
  add_ok=1
  while [ $attempt -lt $max_attempts ]; do
    attempt=$((attempt+1))
    LOG "create_test_users: running 'openhab:users add' (attempt $attempt/$max_attempts)"
    if karaf_exec "openhab:users add $username $password ${group:-user};" >/tmp/karaf_users_add_out 2>&1; then
      LOG "Added user '$username'"
      add_ok=0
      break
    fi
    rc=$?
    LOG "create_test_users: 'openhab:users add' failed (rc=$rc). Output saved to /tmp/karaf_users_add_out"
    # If output mentions 'already exists', treat as success
    if grep -qi "already exists" /tmp/karaf_users_add_out 2>/dev/null; then
      LOG "User '$username' already exists (detected from karaf output)"
      add_ok=0
      break
    fi
    # If it's a transient network/connection reset, retry after adaptive delay
    if grep -qiE "connection reset|connection refused|broken pipe|timed out" /tmp/karaf_users_add_out 2>/dev/null; then
      LOG "create_test_users: transient SSH error detected; will retry"
      # Use adaptive backoff: 0.5s first attempt, 1s second, 2s thereafter
      local backoff_delay="0.5"
      if [ $attempt -eq 2 ]; then
        backoff_delay="1.0"
      elif [ $attempt -gt 2 ]; then
        backoff_delay="2.0"
      fi
      read -t "$backoff_delay" -N 1 < /dev/null 2>/dev/null || true
      continue
    fi
    # unknown failure -> don't retry further
    break
  done

  if [ $add_ok -ne 0 ]; then
    LOG "create_test_users: Failed to add user after $max_attempts attempts; see /tmp/karaf_users_add_out"
    LOG "--- BEGIN /tmp/karaf_users_add_out ---"
    sed -n '1,200p' /tmp/karaf_users_add_out 2>/dev/null || true
    LOG "---  END  /tmp/karaf_users_add_out ---"
    return 1
  fi
}

########## Main ##########

main() {
  LOG "Running setup_user.sh for OpenHAB Karaf SSH and user setup"

  # Ensure we have the required authentication method
  if [ -z "${KARAF_PASSWORD:-}" ]; then
    LOG "Warning: KARAF_PASSWORD not set. Password authentication will not be available."
    if [ -z "${KARAF_SSH_KEY:-}" ]; then
      LOG "Warning: Neither KARAF_PASSWORD nor KARAF_SSH_KEY is set. Authentication may fail."
    fi
  fi

  # Setup SSH key for Karaf authentication (optional fallback)
  setup_karaf_ssh_key

  # Create karaf test users
  create_test_users
  
  LOG "User setup completed."
}

main "$@"