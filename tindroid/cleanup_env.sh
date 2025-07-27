#!/bin/bash
set -e

echo "Cleaning up Tinode environment"
echo "==================="

echo "Stopping all services..."
docker-compose down -v

echo "Removing any dangling containers..."
docker container prune -f

echo "Cleanup complete!" 
echo "==================="