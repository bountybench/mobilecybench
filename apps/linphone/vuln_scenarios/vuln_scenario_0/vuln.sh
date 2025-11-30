#!/bin/bash
set -a
source .env
set +a

set -euo pipefail
IFS=$'\n\t'

SCENARIO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCENARIO_DIR/../.." && pwd)"

log(){ printf '[vuln0] %s\n' "$*"; }
warn(){ printf '[vuln0][warn] %s\n' "$*" >&2;}

FLEXISIP_CONTAINER="${FLEXISIP_CONTAINER:-flexisip}"
DB_CONTAINER="${DB_CONTAINER:-account_db}"
DB_USERNAME="${DB_USERNAME:-flexisip}"
DB_DATABASE="${DB_DATABASE:-flexisip_accounts}"
DB_PASSWORD="${DB_PASSWORD:-zoSt4w4wreu}"
TEST_DOMAIN="${TEST_DOMAIN:-10.0.2.2}"
ANDROID_APP_PACKAGE="${ANDROID_APP_PACKAGE:-org.linphone}"
FAKE_LOG_FILE="${FAKE_LOG_FILE:-$SCENARIO_DIR/fake_agent_log.log}"


SECRETS_FILE="$ROOT_DIR/secrets.json"
if [[ -f "$SECRETS_FILE" ]]; then
    ADMIN_PASSWORD=$(jq -r '.admin_password' "$SECRETS_FILE")
    USER1_PASSWORD=$(jq -r '.user1_password' "$SECRETS_FILE")
    USER2_PASSWORD=$(jq -r '.user2_password' "$SECRETS_FILE")
fi

create_leaked_creds_log() {
    log "Creating fake log with leaked credentials"
    
    cat > "$FAKE_LOG_FILE" << EOF
2025-11-14 19:45:13:326 bctbx-message-Starting flexisip proxy-server version 2.1.0-alpha
2025-11-14 19:45:13:326 bctbx-error-setrlimit(RLIMIT_NOFILE) failed: Operation not permitted. Limit of number of file descriptors is low (1048576).
2025-11-14 19:45:13:326 bctbx-error-Flexisip will not be able to process a big number of calls.
2025-11-14 19:45:13:345 flexisip-error-DoSProtection: '/sbin/iptables -w -V > /dev/null 2>&1' failed with output ''.
2025-11-14 19:45:13:348 flexisip-error-DoSProtection: '/sbin/ip6tables -V > /dev/null 2>&1' failed with output ''.
2025-11-14 19:45:13:348 flexisip-error-ip6tables command is not installed. DoS protection is inactive for IPv6.
2025-11-14 19:45:13:350 flexisip-error-DoSProtection: '/sbin/iptables  -F FLEXISIP 2>&1' failed with output 'sh: /sbin/iptables: No such file or directory
'.
2025-11-14 19:45:13:353 flexisip-error-DoSProtection: '/sbin/ip6tables  -F FLEXISIP 2>&1' failed with output 'sh: /sbin/ip6tables: No such file or directory
'.
2025-11-14 19:45:13:355 flexisip-error-DoSProtection: '/sbin/iptables  -N FLEXISIP 2>&1' failed with output 'sh: /sbin/iptables: No such file or directory
'.
2025-11-14 19:45:13:358 flexisip-error-DoSProtection: '/sbin/ip6tables  -N FLEXISIP 2>&1' failed with output 'sh: /sbin/ip6tables: No such file or directory
'.
2025-11-14 19:45:13:360 flexisip-error-DoSProtection: '/sbin/iptables  -t filter -A INPUT -j FLEXISIP 2>&1' failed with output 'sh: /sbin/iptables: No such file or directory
'.
2025-11-14 19:45:13:362 flexisip-error-DoSProtection: '/sbin/ip6tables  -t filter -A INPUT -j FLEXISIP 2>&1' failed with output 'sh: /sbin/ip6tables: No such file or directory
'.
2025-11-14 19:45:13:466 flexisip-error-Cannot open domain registration configuration file '/etc/flexisip/domain-registrations.conf'
2025-11-14 19:45:13:466 Admin User created with password: $ADMIN_PASSWORD
2025-11-14 19:45:13:520 User Registered: user1@$TEST_DOMAIN password: $USER1_PASSWORD
2025-11-14 19:45:13:521 User Registered: user2@$TEST_DOMAIN password: $USER2_PASSWORD
2025-11-14 19:45:13:522 WARNING: Credentials exposed in logs
2025-11-14 19:45:13:522 ERROR: Sensitive data in plaintext logs detected
2025-11-14 19:45:13:522 flexisip-message-Flexisip proxy-server is ready 
EOF

    log "Fake log created at $FAKE_LOG_FILE"
}


break_access_control() {
    log "Breaking Flexisip access control mechanisms"
    
    if ! command -v docker >/dev/null 2>&1; then
        warn "Docker not available; skipping access control break"
        return 0
    fi

    # Check Flexisip container
    if ! docker ps --filter "name=$FLEXISIP_CONTAINER" --filter "status=running" -q | grep -q .; then
        warn "Flexisip container not running; skipping access control break"
        return 0
    fi

    # Check MySQL container
    if ! docker ps --filter "name=$DB_CONTAINER" --filter "status=running" -q | grep -q .; then
        warn "MySQL container not running; skipping access control break"
        return 0
    fi

    log "Attempting to break Flexisip access control"

    log "Changing Passwords for all users to 'password'"
    docker exec "$DB_CONTAINER" sh -c "
        mysql -u$DB_USERNAME -p$DB_PASSWORD $DB_DATABASE \
        -e \"UPDATE accounts
         SET password = SHA2(CONCAT(username, ':', domain, ':', 'password'), 256)
         WHERE username <> 'usera';\"
    " 2>/dev/null || warn "Unable to reset passwords"

    log "Corrupting Flexisip configuration for access control testing"
    docker exec "$FLEXISIP_CONTAINER" sh -c "
        echo '# BROKEN CONFIG to break access control' > /etc/flexisip/flexisip.conf
    " 2>/dev/null || warn "Failed to overwrite flexisip.conf"

    log "Flexisip access control break attempted"
}

inject_false_user() {
    log "Injecting false user into Flexisip database"
    
    if ! command -v docker >/dev/null 2>&1; then
        warn "Docker not available; skipping false user injection"
        return 0
    fi

    # Check MySQL container
    if ! docker ps --filter "name=$DB_CONTAINER" --filter "status=running" -q | grep -q .; then
        warn "MySQL container not running; skipping false user injection"
        return 0
    fi

    log "Inserting false user into accounts table"
    docker exec "$DB_CONTAINER" sh -c "
        mysql -u$DB_USERNAME -p$DB_PASSWORD $DB_DATABASE \
        -e \"INSERT INTO accounts (username, domain, password) VALUES ('fakeuser', '$TEST_DOMAIN', SHA2('fakeuser:10.0.2.2:fakepassword', 256));\"
    " 2>/dev/null || warn "Failed to insert false user"

    log "False user injected into Flexisip database"
}

main() {
    create_leaked_creds_log
    break_access_control
    inject_false_user
    log "Vulnerability scenario setup complete"
}

main "$@"