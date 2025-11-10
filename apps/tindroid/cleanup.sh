#!/bin/bash
set -e

echo "Cleaning up Tinode environment"
echo "==================="

echo "Stopping all services..."
docker compose down -v

echo "Removing any dangling containers..."
docker container prune -f

echo "Uninstalling Android app..."
adb uninstall co.tinode.tindroidx 2>/dev/null || echo "App not installed or already uninstalled"

APK_PATH="tindroid-debug.apk" # should match APK_PATH in setup_app_apklink.sh
if [ -f "$APK_PATH" ]; then
    echo "Removing downloaded APK: $APK_PATH"
    rm -f "$APK_PATH"
fi

if [ -f "secrets.json" ]; then
    echo "Replacing generated secrets with placeholders in secrets.json..."
    # Use jq to create a temp version with same keys but temp values
    if command -v jq &> /dev/null; then
        # Create temp values based on key type and name patterns
        jq 'to_entries | map({
            key: .key,
            value: (
                if .value | type == "string" then
                    if .key | test("email") then "temp@example.com"
                    elif .key | test("phone|tel") then "+1000000000"
                    elif .key | test("password") then "temp_password"
                    elif .key | test("hash") then "$2a$10$temp.hash.value.here"
                    elif .key | test("generated_at|created_at") then "2025-01-01T00:00:00"
                    elif .key | test("message") then "temp_message"
                    else "temp_" + .key
                    end
                elif .value | type == "number" then 0
                elif .value | type == "boolean" then false
                elif .value | type == "array" then []
                elif .value | type == "object" then {}
                else "temp"
                end
            )
        }) | from_entries' secrets.json > secrets.json.tmp && mv secrets.json.tmp secrets.json
        echo "Created temp secrets.json with same structure"
    else
        # Fallback: create a minimal temp file if jq is not available
        echo '{"note": "temp secrets file - original structure not preserved (jq not available)"}' > secrets.json
        echo "Created minimal temp secrets.json (jq not available)"
    fi
fi

if [ -f ".env" ]; then
    echo "Removing generated environment variables: .env"
    rm -f ".env"
fi

if [ -f "init-db.sql" ]; then
    echo "Removing generated db init script: init-db.sql"
    rm -f "init-db.sql"
fi

if [ -f "seed_secrets.sql" ]; then
    echo "Removing generated seed DB: seed_secrets.sql"
    rm -f "seed_secrets.sql"
fi

if [ -f "scores.json" ]; then
    echo "Removing scores: scores.json"
    rm -f "scores.json"
fi

echo "Removing log files recursively..."
find . -type f -name "*.log" -delete

echo "Removing virtual environment..."
rm -rf ./venv

echo "Cleanup complete!" 
echo "==================="