#!/bin/bash
set -e

# Install Python dependencies globally 
echo "Installing required Python packages..."
pip3 install psycopg2-binary bcrypt requests 2>/dev/null || {
    echo "installing packages failed..."
    exit 1
}

echo "Running Docker compose..."
docker compose up --build -d

echo "Setting up app..."
./setup_app.sh