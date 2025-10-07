#!/bin/bash
set -e

echo "Cleaning up SimpleLogin environment"
echo "==================="

DC="docker compose"

echo "Stopping all services..."
$DC down -v 2>/dev/null || true

echo "Removing any dangling containers..."
docker container prune -f 2>/dev/null || true

echo "Removing test result files..."
rm -f *_results.json 2>/dev/null || true

echo "Removing log files..."
find . -type f -name "*.log" -delete 2>/dev/null || true

echo "Cleanup complete!"
echo "==================="