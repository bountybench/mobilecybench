#!/bin/bash

# Parse command line arguments
SETUP_TYPE=${1:-apklink}  # Default to 'apklink' if no argument provided

# Validate argument
if [[ "$SETUP_TYPE" != "source" && "$SETUP_TYPE" != "apklink" ]]; then
    echo "Error: Invalid setup type '$SETUP_TYPE'"
    echo "Usage: $0 [source|apklink]"
    echo "  source  - Setup app from source code (default)"
    echo "  apklink - Setup app from APK link"
    exit 1
fi

# Run general setup script to get ./start_emulator.sh and ./check_device.sh
chmod +x ../../setup.sh && ./../../setup.sh

# Create fresh volumes
mkdir seadoc-data
mkdir seafile-caddy
mkdir seafile-data
mkdir -p seafile-mysql/db
echo "Created fresh volumes..."

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

# Setup the app based on the specified type
echo "Setting up app using '$SETUP_TYPE' method..."
if [[ "$SETUP_TYPE" == "source" ]]; then
    chmod +x setup_app_source.sh && ./setup_app_source.sh
else
    chmod +x setup_app_apklink.sh && ./setup_app_apklink.sh
fi
