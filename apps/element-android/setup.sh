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

echo "Building Element Android APK..."
./setup_app_apklink.sh

echo "Installing Element Android APK..."
adb install -r apk/element-android.apk

echo "Element Android setup complete!"
echo ""
echo "Matrix homeserver available at: http://localhost:8008"
echo "Element Web interface available at: http://localhost:8080"
echo ""
echo "Test users available:"
echo "- @agent:localhost / agentpass123"
echo "- @alice:localhost / alicepass123"
echo "- @bob:localhost / bobpass123"
echo "- @admin:localhost / adminpass123 (admin)"
