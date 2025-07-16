#!/bin/bash

chmod +x ./create_fresh_volume_dirs.sh && ./create_fresh_volume_dirs.sh
echo "✅ Fresh volume dirs created."
echo "======================="

docker compose up -d --force-recreate --build
echo "✅ Docker containers started."
echo "======================="