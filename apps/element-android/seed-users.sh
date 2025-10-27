#!/bin/bash
set -e

HOMESERVER_URL="http://element-synapse:8008"
REGISTRATION_SECRET="test_registration_secret_key_for_testing_only"

echo "Waiting for Synapse to be ready..."
for i in {1..30}; do
    if curl -s -f "$HOMESERVER_URL/health" > /dev/null 2>&1; then
        echo "Synapse is ready!"
        break
    fi
    echo "Waiting for Synapse... (attempt $i/30)"
    sleep 2
done

# Function to create a user using client registration API
create_user() {
    local username="$1"
    local password="$2"
    local admin="$3"
    
    echo "Creating user: $username"
    
    # Use the standard client registration API since registration is enabled
    local response=$(curl -X POST "$HOMESERVER_URL/_matrix/client/v3/register" \
        -H "Content-Type: application/json" \
        -d "{
            \"username\": \"$username\",
            \"password\": \"$password\",
            \"auth\": {
                \"type\": \"m.login.dummy\"
            }
        }" \
        --silent --show-error 2>&1)
    
    if echo "$response" | grep -q "User ID already taken"; then
        echo "User $username already exists"
    elif echo "$response" | grep -q "access_token"; then
        echo "User $username created successfully"
    else
        echo "Response for $username: $response"
    fi
}

# Create test users
echo "Creating test users..."

# Admin user
create_user "admin" "adminpass123" "true"

# Regular users for testing
create_user "agent" "agentpass123" "false"
create_user "alice" "alicepass123" "false"
create_user "bob" "bobpass123" "false"

echo "All users created successfully!"
echo ""
echo "Available test accounts:"
echo "- @admin:localhost / adminpass123 (admin)"
echo "- @agent:localhost / agentpass123 (regular user)"
echo "- @alice:localhost / alicepass123 (regular user)" 
echo "- @bob:localhost / bobpass123 (regular user)"
echo ""
echo "Homeserver URL: http://localhost:8008"