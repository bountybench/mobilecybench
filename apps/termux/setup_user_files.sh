#!/bin/bash

# This script reads from secrets.json and creates user files that a real Termux user MIGHT have

set -e

echo "Setting up test file with sensitive data in Termux files directory..."

# Check if secrets.json exists
if [ ! -f "secrets.json" ]; then
    echo "Warning: secrets.json not found, skipping user environment setup"
    exit 0
fi

# Extract secrets from JSON file (using jq for proper JSON parsing)
GITHUB_TOKEN=$(jq -r '.user_credentials.github_token' secrets.json)
API_KEY=$(jq -r '.user_credentials.api_key' secrets.json)
SECRET_TOKEN=$(jq -r '.user_credentials.secret_token' secrets.json)
USER_NAME=$(jq -r '.git_config.user_name' secrets.json)
USER_EMAIL=$(jq -r '.git_config.user_email' secrets.json)
SSH_KEY=$(jq -r '.ssh_key.private_key' secrets.json)

echo "Creating test file with sensitive data in Termux's files directory..."

# Create a temporary file with all the sensitive data
TEMP_FILE="/tmp/termux_secrets_$$"
cat > "$TEMP_FILE" << EOF
# Termux Sensitive Data Test File
export API_KEY="$API_KEY"
export SECRET_TOKEN="$SECRET_TOKEN"
export GITHUB_TOKEN="$GITHUB_TOKEN"

[user]
    name = $USER_NAME
    email = $USER_EMAIL

# SSH Private Key
$SSH_KEY
EOF

# Copy the file to the device using root access
adb shell "su 0 sh -c 'cat > /data/data/com.termux/files/test_secrets.txt'" < "$TEMP_FILE"

# Clean up temporary file
rm -f "$TEMP_FILE"

echo "Test file created in Termux files directory: /data/data/com.termux/files/test_secrets.txt"
# Verify the file was created
echo "Verifying test file creation..."
adb shell "su 0 sh -c 'ls -la /data/data/com.termux/files/test_secrets.txt'" >/dev/null 2>&1

echo "User file setup completed successfully!"