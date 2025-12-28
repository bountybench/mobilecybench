#!/bin/bash
set -e

echo "Starting Element Android setup..."

# Create synapse data directory
mkdir -p synapse-data

echo "Starting Matrix Synapse homeserver..."
docker compose up --build -d

echo "Waiting for services to be healthy..."
# Wait for services to be ready
for service in element-postgres element-synapse; do
    echo "Waiting for $service to be healthy..."
    timeout=120
    counter=0
    while [ $counter -lt $timeout ]; do
        health_status="$(docker compose ps --format '{{json .}}' | jq -r 'select(.Name=="'"${service}"'") | .Health // empty')"
        if [ "$health_status" = "healthy" ]; then
            echo "$service is healthy!"
            break
        fi
        sleep 2
        counter=$((counter + 2))
    done
    if [ $counter -ge $timeout ]; then
        echo "ERROR: $service failed to become healthy within ${timeout}s"
        docker compose logs $service
        exit 1
    fi
done

echo "Seeding test users (alice, bob)..."
# User seeding is handled by the element-seeder Docker container (see docker-compose.yml)
# Wait a moment for seeder to complete
sleep 3

echo "Building Element Android APK..."
./setup_app_apklink.sh

echo "Installing Element Android APK..."
# Install the APK that was just downloaded by setup_app_apklink.sh
APK_FILE="apk/element-android.apk"
if [ ! -f "$APK_FILE" ]; then
    echo "ERROR: APK file not found: $APK_FILE"
    exit 1
fi

echo "Installing APK: $APK_FILE"
adb install -r "$APK_FILE"

if [ $? -ne 0 ]; then
    echo "ERROR: Failed to install APK"
    exit 1
fi

echo "Element Android setup complete!"
echo ""
echo "Matrix homeserver available at: http://localhost:8008"
echo "Element Web interface available at: http://localhost:8080"
echo ""
echo "Test users available:"
echo "- @alice:localhost / alicepass123"
echo "- @bob:localhost / bobpass123"
