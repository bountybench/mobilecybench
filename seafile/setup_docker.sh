#!/bin/bash

# Create fresh volumes
chmod +x ./create_fresh_volume_dirs.sh
./create_fresh_volume_dirs.sh
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
