#!/bin/bash

# Parse command line arguments
SETUP_TYPE=${1:-apklink}  # Default to 'apklink' if no argument provided # TEST using source

# Validate argument
if [[ "$SETUP_TYPE" != "source" && "$SETUP_TYPE" != "apklink" ]]; then
    echo "Error: Invalid setup type '$SETUP_TYPE'"
    echo "Usage: $0 [source|apklink]"
    echo "  source  - Setup app from source code (default)"
    echo "  apklink - Setup app from APK link"
    exit 1
fi

# Create fresh volumes
mkdir seadoc-data
mkdir seafile-caddy
mkdir seafile-data
mkdir -p seafile-mysql/db
echo "Created fresh volumes..."

# Check if Docker is running
if ! docker info >/dev/null 2>&1; then
    echo "Docker is not running, starting Docker Desktop now..."
    docker desktop start
    echo "Waiting for Docker to start up..."
    # Wait for Docker to be ready
    while ! docker info >/dev/null 2>&1; do
        echo "Still waiting for Docker..."
        sleep 3
    done
    echo "Docker is now running!"
fi

# Start the server
docker compose up -d --force-recreate --build
echo "Started the server..."
echo "Waiting 20s for server to get up and running..."
for i in {1..20}; do
    echo '.'
    sleep 1
done

# Seed the server with data
python seed_data.py
echo "Seeded the server with data..."
echo "======================="

# Check if Android emulator is running
if ! adb devices | grep -q "emulator"; then
    echo "Android emulator is not running, starting emulator now..."
    chmod +x ../../start_emulator.sh && ../../start_emulator.sh
    echo "Waiting for emulator to be ready..."
    # Wait for emulator to be fully booted
    adb wait-for-device
    while [[ $(adb shell getprop sys.boot_completed 2>/dev/null) != "1" ]]; do
        echo "Still waiting for emulator to boot completely..."
        sleep 3
    done
    echo "Emulator is now ready!"
fi

# Setup the app based on the specified type
echo "Setting up app using '$SETUP_TYPE' method..."
if [[ "$SETUP_TYPE" == "source" ]]; then
    chmod +x setup_app_source.sh && ./setup_app_source.sh
else
    chmod +x setup_app_apklink.sh && ./setup_app_apklink.sh
fi
