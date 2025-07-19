#!/bin/bash

# Create fresh volumes
chmod +x ./create_fresh_volume_dirs.sh
./create_fresh_volume_dirs.sh
echo "Created fresh volumes..."

# Set the server to work from host
sed -i '' 's/10\.0\.2\.2:8000/127\.0\.0\.1:8000/g' .env
echo "Set the server to work from host..."

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

# Stop the server
docker compose down
echo "Stopped the server..."

# Set the server to work from emulator
sed -i '' 's/127\.0\.0\.1:8000/10\.0\.2\.2:8000/g' .env
echo "Set the server to work from emulator..."

# Start the server
docker compose up -d
echo "Started the server..."
echo "======================="
