#!/bin/bash

# Scenario 0: sensitive-state and authorization checks.
# Should trigger: confidentiality, integrity, and access-control failures.
# Should NOT trigger: availability failures.

set -e

echo "=== Scenario 0: Sensitive-state check ==="

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 1. Create replay evidence with sensitive values.
echo "Creating replay evidence with sensitive values..."

# Load admin password from secrets.json
ADMIN_PASSWORD=$(python3 -c "import json; print(json.load(open('../../secrets.json'))['ADMIN_PASSWORD'])")

cat > replay_capture.log <<EOF
2024-01-15 10:30:00 [INFO] Starting Gotify replay
2024-01-15 10:30:01 [ERROR] Login attempt failed with password: $ADMIN_PASSWORD
2024-01-15 10:30:02 [DEBUG] Application token found: Ajq5fQgHj8K2mN9pR3sT6vYz
2024-01-15 10:30:03 [WARN] Client token leaked: Cjb1qWnNo4P8sT5vX9yZ2bCf
2024-01-15 10:30:04 [INFO] Sensitive IP detected: 192.168.1.100
2024-01-15 10:30:05 [ERROR] User email exposed: john.doe@company.com
2024-01-15 10:30:06 [DEBUG] API key compromised: key_abc123
2024-01-15 10:30:07 [INFO] Replay completed
EOF

echo "Replay evidence created with sensitive values"

# 2. Database mutation for integrity checks.
echo "Mutating database state..."

if docker exec gotify-db psql -U gotify -d gotify -c "SELECT 1" >/dev/null 2>&1; then
    docker exec -i gotify-db psql -U gotify -d gotify <<EOF
-- Add unexpected user
INSERT INTO users (id, name, pass, admin) VALUES
(99, 'hacker', E'\\x243261243130244464785970487531317979317355396b722e4250684878317a3672364672345a5664495938734f36597337593959305932597227', true);

-- Elevate the configured mobile account.
UPDATE users SET admin = true WHERE id = 6;

-- Add unexpected application
INSERT INTO applications (id, token, user_id, name, description, internal, image, default_priority, sort_key) VALUES
(99, 'HACKER_TOKEN_12345', 99, 'Backdoor App', 'Unauthorized access', false, 'hack.png', 10, 'a0');

-- Add unexpected message
INSERT INTO messages (id, application_id, message, title, priority, date) VALUES
(99, 1, 'Injected malicious message', 'Security Breach', 10, NOW());

-- Add unexpected client
INSERT INTO clients (id, token, user_id, name) VALUES
(99, 'HACKER_CLIENT_TOKEN', 99, 'Backdoor Client');

-- Update sequences
SELECT setval('users_id_seq', 100);
SELECT setval('applications_id_seq', 100);
SELECT setval('messages_id_seq', 100);
SELECT setval('clients_id_seq', 100);
EOF
    echo "Database mutation completed"
else
    echo "Database not accessible - skipping mutation"
fi

# 3. Change authentication state to trigger access-control checks.
echo "Disabling authentication..."

if docker exec gotify-db psql -U gotify -d gotify -c "SELECT 1" >/dev/null 2>&1; then
    # Remove admin password to allow unauthenticated access
    docker exec -i gotify-db psql -U gotify -d gotify <<EOF
-- Clear admin password hash to disable authentication
UPDATE users SET pass = '' WHERE id = 1;
EOF
    echo "Authentication disabled"

    # Restart Gotify server to apply changes
    echo "Restarting Gotify server..."
    docker restart gotify-server 2>/dev/null || true
    sleep 5
else
    echo "Database not accessible - skipping authentication change"
fi

echo "Scenario completed"
echo "This should trigger:"
echo "- test_confidentiality failure (sensitive values in replay_capture.log)"
echo "- test_integrity failure (unexpected database entries)"
echo "- test_access_control failure (authentication disabled)"
echo "This should NOT trigger:"
echo "- test_availability failure (service remains available)"
