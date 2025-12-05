#!/bin/bash
# Create users for docker-mailserver
# This script adds email accounts to the mail server

set -e

CONTAINER_NAME="deltachat-mailserver"
LOG_PREFIX="[setup_mailserver_users]"

log() { printf '%s %s\n' "$LOG_PREFIX" "$*"; }
error() { printf '%s[error] %s\n' "$LOG_PREFIX" "$*" >&2; exit 1; }

# Wait for container to be ready
wait_for_container() {
    log "Waiting for $CONTAINER_NAME to be ready..."
    for i in {1..30}; do
        if docker exec "$CONTAINER_NAME" test -f /var/run/dovecot/master.pid 2>/dev/null; then
            log "Container is ready"
            return 0
        fi
        sleep 2
    done
    error "Container not ready after 60 seconds"
}

# Add a user to the mail server
add_user() {
    local email="$1"
    local password="$2"
    
    log "Adding user: $email"
    if docker exec "$CONTAINER_NAME" setup email add "$email" "$password" 2>/dev/null; then
        log "Successfully added user: $email"
        return 0
    else
        # User might already exist, try updating password
        log "User may already exist, attempting to update: $email"
        docker exec "$CONTAINER_NAME" setup email update "$email" "$password" 2>/dev/null || true
        return 0
    fi
}

main() {
    wait_for_container
    
    # Add users from accounts.json
    add_user "user1@deltachat.test" "whynotthispasscode123"
    add_user "user2@deltachat.test" "xK9mPq2vL7nR4wYz"
    add_user "user3@deltachat.test" "bT5hJc8sN3fG6dAe"
    
    log "All users configured successfully"
}

main "$@"

